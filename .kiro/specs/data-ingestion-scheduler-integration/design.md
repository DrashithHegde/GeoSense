# Data Ingestion Scheduler Integration Bugfix Design

## Overview

The GeoSense data ingestion pipeline has a fully functional scheduler (`server/scripts/scheduler.py`) with robust ingestion scripts, but the scheduler is not integrated with the FastAPI application lifecycle. This means data ingestion does not run automatically—developers must manually invoke the scheduler script. The bug manifests in both development and production environments: no automated data freshness, requiring manual intervention to populate the database with current environmental observations.

This design addresses the integration gap by connecting the existing scheduler infrastructure to FastAPI's lifecycle hooks, implementing proper error handling that preserves application stability, and providing different invocation strategies for development (manual trigger acceptable) versus production (automated scheduling required).

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug - when the FastAPI application starts without automatically initiating the data ingestion scheduler
- **Property (P)**: The desired behavior - scheduler runs automatically in production mode while remaining controllable in development
- **Preservation**: Existing 76+ passing tests, upsert-based idempotent ingestion, and error isolation that must remain unchanged by the fix
- **`run_scheduler()`**: The infinite-loop function in `server/scripts/scheduler.py` that orchestrates AQI, Sentinel-2, Landsat, and feature/anomaly pipeline execution
- **`run_aqi_cycle()`**: Function that fetches AQICN data and derives the IDW grid
- **Startup Hook**: FastAPI's `@app.on_event("startup")` decorator that executes code when the application initializes
- **Background Task**: A separate thread or process that runs concurrently with the main FastAPI application
- **Environment Mode**: Configuration distinguishing development (DEV) from production (PROD) execution contexts

## Bug Details

### Bug Condition

The bug manifests when the FastAPI application starts (`server/app/main.py`). The application initializes successfully and serves API requests, but the data ingestion scheduler never executes. The `run_scheduler()` function exists and works correctly when manually invoked, but there is no automatic invocation mechanism integrated with the application lifecycle.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type ApplicationStartupEvent
  OUTPUT: boolean
  
  RETURN application.started == True
         AND scheduler_thread.exists() == False
         AND environment_mode IN ['development', 'production']
         AND NOT scheduler_manually_invoked
END FUNCTION
```

### Examples

- **Development startup**: Developer runs `uvicorn app.main:app --reload`. The API starts on port 8000, database connection succeeds, but no AQI/satellite data ingestion occurs. Database remains stale until developer manually runs `python server/scripts/scheduler.py`.

- **Production startup**: Application deployed to a server, FastAPI starts successfully, API endpoints respond correctly, but `environment_data` table receives no new observations. After 3 hours, AQI data is outdated; after 7 days, Sentinel-2 data is missing; after 14 days, Landsat data is unavailable.

- **Manual invocation works**: Running `python server/scripts/scheduler.py` from command line successfully executes all ingestion cycles, demonstrates scheduler logic is functional.

- **Edge case - Server restart**: Server restarts (crash recovery, deployment update, or maintenance reboot). Application comes back online but scheduler doesn't resume, creating a data freshness gap proportional to downtime duration.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- All 76+ existing tests must continue to pass without modification
- Idempotent upsert-based ingestion must remain unchanged (ON CONFLICT DO UPDATE logic)
- Scheduler error handling that logs failures without crashing must be preserved
- Individual ingestion script interfaces (run_aqi_cycle, run_derivation, run_ndvi_ndwi_ingest, run_lst_ingest, run_feature_anomaly_pipeline) must remain callable independently for diagnostic purposes
- FastAPI application must start successfully even if scheduler initialization fails
- Database connection verification on startup must continue to work
- API request handling must not be blocked by scheduler execution

**Scope:**
All functionality that does NOT involve automatic scheduler execution should be completely unaffected by this fix. This includes:
- Manual script invocation from command line
- API endpoint behavior
- Database query performance
- Test execution environment (tests should not trigger actual scheduler execution)
- Existing logging format and level
- CORS configuration
- Application shutdown behavior

## Hypothesized Root Cause

Based on the code structure and bug description, the most likely issues are:

1. **Missing Lifecycle Integration**: The `server/app/main.py` file has a `@app.on_event("startup")` hook for database verification but no scheduler initialization. The scheduler exists as a standalone script with no connection point to the application lifecycle.

2. **Blocking Execution Concern**: Developers may have intentionally avoided integrating the scheduler because `run_scheduler()` contains an infinite `while True` loop with `time.sleep(POLL_SECONDS)`. Calling this directly in a startup hook would block the entire FastAPI application from serving requests.

3. **No Environment-Based Configuration**: There is no configuration mechanism to distinguish development (where manual trigger may be acceptable) from production (where automated scheduling is required). The application cannot conditionally enable the scheduler based on deployment context.

4. **Unclear Threading/Process Strategy**: Even if developers wanted to integrate the scheduler, the optimal approach is ambiguous: background thread (lightweight but shares GIL), separate process (isolated but requires IPC), task queue (robust but adds dependency complexity), or external process manager (simple but requires deployment changes).

## Correctness Properties

Property 1: Bug Condition - Scheduler Auto-Starts in Production Mode

_For any_ application startup where the environment mode is set to production and the FastAPI application initializes successfully, the fixed application SHALL automatically start the scheduler in a non-blocking manner, ensuring data ingestion cycles execute according to their configured intervals (AQI every 3 hours, Sentinel-2 every 7 days, Landsat every 14 days) without manual intervention.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - Application Functionality and Test Suite

_For any_ application behavior that does NOT involve automatic scheduler execution (manual script invocation, API request handling, database operations, test execution), the fixed code SHALL produce exactly the same behavior as the original code, preserving all existing functionality including the complete 76+ test suite passing without modification.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `server/app/main.py`

**Function**: Application startup and lifecycle management

**Specific Changes**:

1. **Add Environment Configuration**:
   - Extend `server/app/core/config.py` to include `SCHEDULER_ENABLED: bool` with default `False` and `SCHEDULER_MODE: str` with options `['disabled', 'thread', 'manual']`
   - Allow environment variable `GEOSENSE_SCHEDULER_ENABLED=true` for production deployments
   - Preserve development default of `disabled` to avoid unexpected behavior during testing

2. **Create Scheduler Wrapper Module**:
   - Create `server/app/services/scheduler_integration.py` with:
     - `start_scheduler_background()`: Launches `run_scheduler()` in a daemon thread
     - `shutdown_scheduler()`: Gracefully stops the scheduler (add stop signal to scheduler loop)
     - Proper exception handling that logs errors without crashing the application
   - This isolates scheduler integration from main application logic

3. **Modify Scheduler for Graceful Shutdown**:
   - Add `threading.Event` stop signal to `server/scripts/scheduler.py`
   - Change `while True:` to `while not stop_event.is_set():`
   - This allows clean shutdown without abruptly killing the thread

4. **Integrate with FastAPI Lifecycle**:
   - Update `@app.on_event("startup")` in `main.py` to conditionally start scheduler based on config
   - Add `@app.on_event("shutdown")` hook to signal scheduler stop
   - Ensure startup continues even if scheduler fails to initialize (log error but don't raise exception)

5. **Add Startup Logging**:
   - Log scheduler status at startup: `"Scheduler: enabled (mode: thread)"` or `"Scheduler: disabled (development mode)"`
   - This provides visibility into whether automatic ingestion is active

### Configuration Example

**Development** (`.env`):
```
GEOSENSE_SCHEDULER_ENABLED=false
# Scheduler remains manual for faster iteration
```

**Production** (`.env` or environment variables):
```
GEOSENSE_SCHEDULER_ENABLED=true
GEOSENSE_SCHEDULER_MODE=thread
# Scheduler auto-starts in background thread
```

**Alternative Production Strategy** (deployment documentation):
```
# Option: Run scheduler as separate process
# Supervisor/systemd runs both:
#   - uvicorn app.main:app (API server)
#   - python server/scripts/scheduler.py (data ingestion)
```

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, verify the bug exists by demonstrating that the current application does NOT start the scheduler automatically, then verify the fix correctly integrates scheduler execution while preserving all existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Confirm the bug BEFORE implementing the fix by observing that the scheduler does not run automatically when the FastAPI application starts.

**Test Plan**: 
1. Start the FastAPI application using `uvicorn app.main:app` 
2. Observe application logs for any scheduler-related initialization messages
3. Query `environment_data` table for new observations after waiting past an ingestion interval (e.g., 3+ hours for AQI)
4. Check for running threads or background processes related to the scheduler

Run these observations on the UNFIXED code to confirm scheduler never executes.

**Test Cases**:
1. **Startup Without Scheduler**: Start application, verify no scheduler thread exists (will confirm bug on unfixed code)
2. **Data Remains Stale**: Wait 3+ hours after startup, verify no new AQI observations (will confirm bug on unfixed code)
3. **Manual Script Still Works**: Run `python server/scripts/scheduler.py` manually, verify it works correctly (will pass on unfixed code, confirms scheduler logic is sound)
4. **Application Serves Requests**: Start application, make API requests, verify they succeed (will pass on unfixed code, confirms API doesn't depend on scheduler)

**Expected Counterexamples**:
- Application starts successfully but no scheduler-related log messages appear
- No background threads related to data ingestion are created
- Database observations remain stale despite application running for multiple ingestion intervals
- Possible causes: missing lifecycle integration, no threading mechanism, missing configuration

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds (production mode startup), the fixed application automatically starts the scheduler.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := application_startup_fixed(input)
  ASSERT scheduler_thread_exists(result)
  ASSERT scheduler_executing_cycles(result)
  ASSERT no_application_blocking(result)
END FOR
```

**Test Implementation:**
- Unit test: Mock FastAPI startup event with `SCHEDULER_ENABLED=true`, verify `start_scheduler_background()` is called
- Integration test: Start application with production config, check for scheduler thread in process, wait for one ingestion interval, verify new database observation
- Error handling test: Simulate scheduler initialization failure, verify application still starts successfully and logs error

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold (development mode, test environment, API request handling), the fixed application produces the same result as the original application.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT application_original(input) = application_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It automatically tests many combinations of configuration values
- It catches edge cases like partial configuration or missing environment variables
- It provides strong guarantees that existing tests continue to pass
- It validates that API behavior is unchanged across many request patterns

**Test Plan**: 
1. Run the UNFIXED application with default development config, capture API response patterns and behavior
2. Run existing 76+ test suite on UNFIXED code, document passing tests
3. After implementing fix, rerun all tests with `SCHEDULER_ENABLED=false` (development mode)
4. Verify identical behavior: all tests pass, API responses unchanged, no unexpected threads

**Test Cases**:
1. **Existing Test Suite Preservation**: Run all 76+ existing tests with scheduler disabled, verify 100% pass rate (tests should not trigger real scheduler)
2. **API Response Preservation**: Make GET requests to `/api/health`, `/api/anomalies`, `/api/metrics/latest` with scheduler disabled, verify responses match original behavior
3. **Manual Script Preservation**: Run `python server/scripts/scheduler.py` directly after fix, verify it still executes correctly without changes
4. **Development Mode Preservation**: Start application with `SCHEDULER_ENABLED=false`, verify no scheduler thread created, application behaves identically to unfixed version

### Unit Tests

- Test `start_scheduler_background()` creates a daemon thread
- Test `shutdown_scheduler()` sets stop event and thread exits gracefully
- Test configuration loading for `SCHEDULER_ENABLED` and `SCHEDULER_MODE`
- Test startup hook conditionally calls scheduler integration based on config
- Test scheduler initialization failure is caught and logged without crashing application
- Test stop event integration in scheduler loop exits cleanly

### Property-Based Tests

- Generate random FastAPI startup configurations (enabled/disabled, different modes), verify correct scheduler behavior for each
- Generate random environment variable combinations, verify application always starts successfully regardless of scheduler state
- Generate random API request patterns, verify scheduler presence/absence does not affect response correctness
- Generate random scheduler error scenarios (missing dependencies, network failures), verify application remains stable

### Integration Tests

- Test full application startup with scheduler enabled in production mode
- Test that AQI cycle executes after configured interval when scheduler is running
- Test that application continues serving API requests while scheduler runs in background
- Test graceful shutdown properly stops scheduler thread before application exits
- Test application restart resumes scheduler execution without data loss
- Test that database upsert logic remains idempotent when scheduler runs automatically
- Test manual script invocation works correctly alongside automatic scheduler (e.g., for emergency data refresh)
