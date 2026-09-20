# Implementation Plan

## Overview
This task list implements the scheduler integration bugfix following the exploratory bugfix workflow. The bug manifests when FastAPI starts without automatically initiating the data ingestion scheduler, requiring manual intervention for data freshness. We'll first explore the bug with tests, write preservation tests, then implement the fix while maintaining the 76+ passing test baseline.

---

## Phase 1: Bug Condition Exploration

- [ ] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Scheduler Does Not Auto-Start on Application Startup
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate scheduler never starts automatically
  - **Scoped PBT Approach**: Test concrete startup scenarios (development mode, production mode, default config)
  - Create test file `server/tests/test_scheduler_integration.py`
  - Test implementation:
    - Mock FastAPI application startup event
    - Verify no scheduler thread exists after startup in current code
    - Verify no background task is created for scheduler execution
    - Check that `run_scheduler()` is never called during application lifecycle
    - Test both `env='development'` and `env='production'` configurations
  - The test assertions should match the Expected Behavior Properties from design:
    - In production mode: scheduler thread SHOULD exist (will fail on unfixed code)
    - In development mode with manual trigger: scheduler thread may not exist (acceptable)
  - Run test on UNFIXED code with: `pytest server/tests/test_scheduler_integration.py -v`
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists)
  - Document counterexamples found:
    - Application starts successfully but no scheduler initialization occurs
    - No threading.Thread instance related to scheduler is created
    - FastAPI startup hook completes but `run_scheduler()` is never invoked
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 2.1 (Auto-start in production), 2.2 (Non-blocking execution), 2.3 (Runs at configured intervals)_

---

## Phase 2: Preservation Property Tests

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Existing Test Suite and API Behavior Remain Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - **Observation Phase** (run on UNFIXED code):
    - Run existing test suite: `pytest server/tests/ -v --tb=short`
    - Document that all 76+ tests pass on unfixed code
    - Test manual scheduler invocation: `python server/scripts/scheduler.py --dry-run`
    - Verify it outputs schedule description without errors
    - Start FastAPI application without scheduler: `uvicorn app.main:app`
    - Make API requests to key endpoints and document responses:
      - `GET /api/health` returns 200 OK
      - `GET /api/anomalies` returns expected structure
      - `GET /api/metrics/latest` returns latest metrics
  - **Property-Based Test Implementation**:
    - Add tests to `server/tests/test_scheduler_integration.py` for preservation
    - Test 1: All existing tests must pass with scheduler disabled
      - Import and run test discovery programmatically
      - Verify 76+ tests pass when `SCHEDULER_ENABLED=false`
    - Test 2: API endpoints function identically with/without scheduler
      - Generate property tests for common API request patterns
      - Test `/api/health`, `/api/anomalies`, `/api/metrics/*` endpoints
      - Verify responses are identical regardless of scheduler state
    - Test 3: Manual scheduler script remains callable
      - Verify `scheduler.run_scheduler()` can be called directly
      - Verify it executes without import errors or configuration conflicts
    - Test 4: Application startup succeeds with scheduler disabled
      - Start app with `SCHEDULER_ENABLED=false`
      - Verify no scheduler threads created
      - Verify application serves requests normally
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1 (Test suite unchanged), 3.2 (Idempotent upsert), 3.3 (Error handling), 3.4 (Manual invocation), 3.5 (App starts on scheduler failure), 3.6 (DB verification), 3.7 (API not blocked), 3.8 (Test environment isolation)_

---

## Phase 3: Configuration and Setup

- [ ] 3. Add scheduler configuration to settings

  - [ ] 3.1 Extend configuration schema
    - Open `server/app/core/config.py`
    - Add new fields to `Settings` class:
      - `scheduler_enabled: bool = False` (default disabled for development safety)
      - `scheduler_mode: str = "thread"` (options: "thread", "disabled")
    - Add environment variable mapping:
      - `GEOSENSE_SCHEDULER_ENABLED` → `scheduler_enabled`
      - `GEOSENSE_SCHEDULER_MODE` → `scheduler_mode`
    - Add validation: `scheduler_mode` must be in `["thread", "disabled"]`
    - _Bug_Condition: Application starts without scheduler config check_
    - _Expected_Behavior: Configuration allows conditional scheduler activation_
    - _Preservation: Existing config fields and behavior unchanged_
    - _Requirements: 2.1 (production auto-start needs config), 3.1 (preserve existing tests)_

  - [ ] 3.2 Add configuration documentation
    - Update `server/.env.example` with new variables:
      - `# Scheduler Configuration`
      - `# GEOSENSE_SCHEDULER_ENABLED=false  # Set to true in production`
      - `# GEOSENSE_SCHEDULER_MODE=thread    # Options: thread, disabled`
    - Document development vs production settings in comments
    - _Requirements: 2.1 (production needs clear config), 3.4 (manual invocation still supported)_

  - [ ] 3.3 Write configuration tests
    - Create test cases in `server/tests/test_config.py` or add to existing:
      - Test default values (scheduler_enabled=False, mode="thread")
      - Test environment variable parsing
      - Test invalid scheduler_mode raises validation error
      - Test configuration loads correctly from .env file
    - Run tests: `pytest server/tests/test_config.py -v -k scheduler`
    - Ensure all config tests pass
    - _Requirements: 3.1 (tests must pass), 3.8 (test environment safe)_

---

## Phase 4: Scheduler Wrapper Implementation

- [ ] 4. Create scheduler integration service

  - [ ] 4.1 Create scheduler integration module
    - Create new file: `server/app/services/scheduler_integration.py`
    - Implement graceful shutdown mechanism:
      - Create module-level `threading.Event` named `stop_event`
      - Add `get_stop_event() -> threading.Event` function
    - Implement `start_scheduler_background()` function:
      - Accept no parameters (reads from config)
      - Create daemon thread: `threading.Thread(target=_run_scheduler_loop, daemon=True)`
      - Start thread and return thread object
      - Add logging: "Scheduler background thread started"
    - Implement `_run_scheduler_loop()` internal function:
      - Import `run_scheduler` from `server.scripts.scheduler`
      - Wrap in try-except to catch all exceptions
      - Log exceptions without re-raising
      - Call modified scheduler that respects stop event
    - Implement `shutdown_scheduler()` function:
      - Set `stop_event` to signal graceful shutdown
      - Log: "Scheduler shutdown signal sent"
      - Wait up to 5 seconds for thread to exit gracefully
    - Add comprehensive docstrings explaining lifecycle
    - _Bug_Condition: No wrapper exists to run scheduler in background thread_
    - _Expected_Behavior: Scheduler runs in daemon thread without blocking FastAPI_
    - _Preservation: Does not modify existing scheduler.py yet_
    - _Requirements: 2.2 (non-blocking), 2.3 (runs at intervals), 3.3 (error handling preserved), 3.5 (app starts even if scheduler fails)_

  - [ ] 4.2 Modify scheduler for graceful shutdown
    - Open `server/scripts/scheduler.py`
    - Add stop event parameter to `run_scheduler()`:
      - Change signature: `def run_scheduler(stop_event: threading.Event | None = None) -> None:`
      - If `stop_event` is None, create internal event (for backward compatibility)
    - Modify main loop:
      - Change `while True:` to `while not stop_event.is_set():`
      - Check stop event before each sleep: `if stop_event.wait(POLL_SECONDS): break`
    - Add logging on graceful exit: "Scheduler received shutdown signal, exiting cleanly"
    - Ensure backward compatibility: manual script invocation still works
    - _Bug_Condition: Scheduler has infinite loop with no exit mechanism_
    - _Expected_Behavior: Scheduler can be stopped gracefully_
    - _Preservation: Manual invocation behavior unchanged (stop_event=None default)_
    - _Requirements: 2.2 (non-blocking with clean shutdown), 3.4 (manual invocation preserved)_

  - [ ] 4.3 Write unit tests for scheduler integration
    - Create comprehensive unit tests in `server/tests/test_scheduler_integration.py`
    - Test `start_scheduler_background()`:
      - Verify it returns a `threading.Thread` object
      - Verify thread is marked as daemon
      - Verify thread is alive after start
      - Mock `run_scheduler` to avoid actual execution
    - Test `shutdown_scheduler()`:
      - Start scheduler background thread
      - Call shutdown
      - Verify stop_event is set
      - Verify thread exits within timeout
    - Test graceful shutdown in scheduler loop:
      - Create stop_event and thread
      - Call `run_scheduler(stop_event)`
      - Set stop_event after 2 seconds
      - Verify loop exits cleanly without exception
    - Test exception handling:
      - Mock scheduler to raise exception
      - Verify exception is logged, not propagated
      - Verify application remains stable
    - Run tests: `pytest server/tests/test_scheduler_integration.py::test_start_scheduler_background -v`
    - _Requirements: 3.1 (new tests must pass), 3.3 (error handling validated), 3.5 (stability on failure)_

---

## Phase 5: FastAPI Lifecycle Integration

- [ ] 5. Integrate scheduler with FastAPI lifecycle

  - [ ] 5.1 Add startup hook integration
    - Open `server/app/main.py`
    - Import dependencies at top:
      - `from app.services.scheduler_integration import start_scheduler_background, shutdown_scheduler`
      - `from app.core.config import get_settings`
    - Create module-level variable: `scheduler_thread: threading.Thread | None = None`
    - Modify existing `@app.on_event("startup")` function or create new one:
      - Rename existing to `verify_database_connection()` (keep as is)
      - Add new `@app.on_event("startup")` function: `start_scheduler_if_enabled()`
      - Get settings: `settings = get_settings()`
      - Check: `if settings.scheduler_enabled and settings.scheduler_mode == "thread":`
      - If true:
        - Try to start scheduler: `scheduler_thread = start_scheduler_background()`
        - Log success: "Scheduler: enabled (mode: thread)"
        - Catch exceptions, log error: "Scheduler failed to start: {exception}"
        - Do NOT raise exception (preserve app startup)
      - If false:
        - Log: "Scheduler: disabled (development mode)"
    - Ensure database verification still runs first
    - _Bug_Condition: No lifecycle integration exists_
    - _Expected_Behavior: Scheduler starts automatically when enabled_
    - _Preservation: Database verification unchanged, app starts even on scheduler failure_
    - _Requirements: 2.1 (auto-start in production), 2.2 (non-blocking), 3.5 (app starts on failure), 3.6 (DB verification preserved)_

  - [ ] 5.2 Add shutdown hook integration
    - In `server/app/main.py`, add shutdown event handler:
      - `@app.on_event("shutdown")`
      - `def stop_scheduler_on_shutdown() -> None:`
      - Check if `scheduler_thread is not None and scheduler_thread.is_alive()`
      - If true, call `shutdown_scheduler()`
      - Log: "Scheduler shutdown complete"
    - Ensure graceful cleanup on application exit
    - _Expected_Behavior: Scheduler stops cleanly on app shutdown_
    - _Preservation: Existing shutdown behavior unchanged_
    - _Requirements: 2.2 (clean lifecycle management)_

  - [ ] 5.3 Add startup logging visibility
    - Enhance logging in startup hook:
      - Log scheduler configuration state
      - Log thread ID when scheduler starts
      - Log any configuration issues clearly
    - Format: `"Scheduler: {status} (mode: {mode}, thread_id: {id})"`
    - _Requirements: 2.1 (visibility into auto-start), 3.5 (clear error reporting)_

  - [ ] 5.4 Write integration tests for lifecycle
    - Add integration tests to `server/tests/test_scheduler_integration.py`
    - Test startup with scheduler enabled:
      - Mock settings: `scheduler_enabled=True, scheduler_mode="thread"`
      - Trigger startup event
      - Verify `start_scheduler_background()` is called
      - Verify no exceptions raised
    - Test startup with scheduler disabled:
      - Mock settings: `scheduler_enabled=False`
      - Trigger startup event
      - Verify `start_scheduler_background()` is NOT called
      - Verify application continues normally
    - Test startup with scheduler failure:
      - Mock `start_scheduler_background()` to raise exception
      - Trigger startup event
      - Verify exception is caught and logged
      - Verify application startup continues (doesn't crash)
    - Test shutdown hook:
      - Start app with scheduler enabled
      - Trigger shutdown event
      - Verify `shutdown_scheduler()` is called
      - Verify stop_event is set
    - Run tests: `pytest server/tests/test_scheduler_integration.py -v -k lifecycle`
    - _Requirements: 3.1 (tests pass), 3.5 (app stability), 3.7 (API not blocked)_

---

## Phase 6: Verification and Validation

- [ ] 6. Fix implementation verification

  - [ ] 6.1 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Scheduler Auto-Starts in Production Mode
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test: `pytest server/tests/test_scheduler_integration.py::test_scheduler_auto_start -v`
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - Verify specific scenarios:
      - Production mode (`scheduler_enabled=true`): scheduler thread exists
      - Development mode (`scheduler_enabled=false`): no scheduler thread
      - Scheduler executes without blocking FastAPI request handling
    - Document that counterexamples from task 1 are now resolved
    - _Requirements: 2.1 (auto-start works), 2.2 (non-blocking), 2.3 (intervals work)_

  - [ ] 6.2 Verify preservation tests still pass
    - **Property 2: Preservation** - All Existing Behavior Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run full preservation test suite: `pytest server/tests/test_scheduler_integration.py -v -k preservation`
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Run full existing test suite with scheduler disabled:
      - `GEOSENSE_SCHEDULER_ENABLED=false pytest server/tests/ -v --tb=short`
      - Verify all 76+ tests pass
      - Confirm no test was modified (except new scheduler integration tests)
    - Test manual scheduler invocation still works:
      - `python server/scripts/scheduler.py --dry-run`
      - Verify output matches original behavior
    - Test API endpoints with scheduler disabled:
      - Start app: `GEOSENSE_SCHEDULER_ENABLED=false uvicorn app.main:app`
      - Make requests to `/api/health`, `/api/anomalies`, `/api/metrics/latest`
      - Verify responses identical to pre-fix behavior
    - Confirm all preservation properties hold

  - [ ] 6.3 End-to-end integration test
    - Create `server/tests/test_scheduler_e2e.py` for full integration test
    - Test complete application lifecycle with scheduler:
      - Start FastAPI with `scheduler_enabled=true, env='production'`
      - Verify scheduler thread is created and alive
      - Mock time progression to trigger AQI cycle
      - Verify scheduler executes `run_aqi_cycle()` (mock GEE/AQICN calls)
      - Make API requests while scheduler is running
      - Verify API responses are correct and not blocked
      - Trigger shutdown
      - Verify scheduler stops gracefully
    - Test idempotent behavior:
      - Run scheduler cycle multiple times
      - Verify database upsert logic handles duplicates correctly
      - Confirm no data corruption or conflicts
    - Run test: `pytest server/tests/test_scheduler_e2e.py -v`
    - _Requirements: 2.1, 2.2, 2.3 (full integration), 3.2 (idempotent upsert), 3.7 (API not blocked)_

  - [ ] 6.4 Manual verification with real application
    - Start application in development mode:
      - `GEOSENSE_SCHEDULER_ENABLED=false uvicorn app.main:app --reload`
      - Verify log shows: "Scheduler: disabled (development mode)"
      - Verify no scheduler thread in process
      - Verify API endpoints work normally
    - Start application in production simulation:
      - `GEOSENSE_SCHEDULER_ENABLED=true GEOSENSE_ENV=production uvicorn app.main:app`
      - Verify log shows: "Scheduler: enabled (mode: thread)"
      - Check process threads: verify daemon thread exists
      - Monitor logs for scheduled cycle execution attempts
      - Make API requests, verify responses while scheduler runs
      - Stop application (Ctrl+C), verify clean shutdown logs
    - Document findings in task comments
    - _Requirements: 2.1 (production auto-start), 2.2 (non-blocking), 2.3 (intervals), 3.7 (API works)_

---

## Phase 7: Documentation and Finalization

- [ ] 7. Documentation and deployment guidance

  - [ ] 7.1 Update application documentation
    - Update `server/README.md` or `developmentguide.md`:
      - Add "Scheduler Integration" section
      - Document environment variables:
        - `GEOSENSE_SCHEDULER_ENABLED`: Enable automatic scheduler (default: false)
        - `GEOSENSE_SCHEDULER_MODE`: Execution mode (default: thread)
      - Document development vs production configuration
      - Explain manual override: `python server/scripts/scheduler.py`
    - Add troubleshooting section:
      - How to verify scheduler is running
      - How to check logs for scheduler activity
      - What to do if scheduler fails to start
    - _Requirements: 2.1 (clear production setup), 3.4 (manual invocation documented)_

  - [ ] 7.2 Create deployment configuration examples
    - Create example production `.env`:
      - `GEOSENSE_SCHEDULER_ENABLED=true`
      - `GEOSENSE_SCHEDULER_MODE=thread`
    - Create example development `.env`:
      - `GEOSENSE_SCHEDULER_ENABLED=false`
      - Comment explaining manual trigger for development
    - Document alternative deployment strategies:
      - Single process with background thread (implemented)
      - Separate process with supervisor/systemd (alternative)
      - Container orchestration considerations
    - _Requirements: 2.1 (production deployment clear)_

  - [ ] 7.3 Add monitoring and observability notes
    - Document how to monitor scheduler health:
      - Log patterns to watch for cycle execution
      - Expected log frequency based on intervals
      - Error patterns that indicate scheduler issues
    - Add recommendations for production monitoring:
      - Alert on missing scheduler logs after expected interval
      - Monitor thread count and memory usage
      - Track data freshness in database
    - _Requirements: 2.3 (interval adherence verifiable)_

---

## Phase 8: Final Checkpoint

- [ ] 8. Checkpoint - Ensure all tests pass and functionality works
  - Run complete test suite: `pytest server/tests/ -v --tb=short`
  - Verify all 76+ original tests still pass
  - Verify all new scheduler integration tests pass
  - Verify end-to-end integration test passes
  - Manual smoke test:
    - Start app with scheduler enabled
    - Verify scheduler starts and logs cycles
    - Make API requests, verify responses
    - Stop app, verify clean shutdown
  - Review all task completion criteria
  - Document any outstanding issues or considerations
  - Confirm fix is complete and ready for deployment
  - Ask user for feedback if any questions or concerns arise
  - _Requirements: All (comprehensive validation)_

---

## Notes

### Task Ordering Rationale
1. **Exploration First** (Tasks 1-2): Understand the bug through failing tests, establish baseline behavior
2. **Configuration** (Task 3): Non-breaking setup that enables conditional behavior
3. **Core Implementation** (Task 4): Build scheduler wrapper with graceful shutdown
4. **Integration** (Task 5): Connect to FastAPI lifecycle hooks
5. **Verification** (Task 6): Validate fix works and nothing breaks
6. **Documentation** (Task 7-8): Finalize with deployment guidance

### Risk Mitigation
- Each task is independently testable
- Configuration defaults preserve development workflow (scheduler disabled)
- Error handling ensures application stability even on scheduler failure
- Preservation tests run continuously to catch regressions
- Manual invocation remains available for debugging

### Key Success Criteria
- ✅ Bug condition test fails on unfixed code, passes after fix
- ✅ All 76+ existing tests continue to pass
- ✅ Scheduler auto-starts in production mode
- ✅ Scheduler runs without blocking API requests
- ✅ Application starts successfully even if scheduler fails
- ✅ Manual script invocation still works for diagnostics
