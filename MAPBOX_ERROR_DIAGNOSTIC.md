# Mapbox Fetch Error Diagnostic

## Problem

Browser console shows 107+ repeated errors:
```
Failed to fetch https://api.mapbox.com/v4/mapbox.mapbox-str...
```

## Diagnostics Added

Enhanced error logging in `client/src/hooks/index.js` to capture:

1. **Mapbox Token Configuration**
   - Token existence
   - Token format validation (starts with 'pk.')
   - Token length
   - Map style being used

2. **Complete Failed URL**
   - Full URL extraction from error messages
   - Resource type identification (vector tile, sprite, glyph, style)
   - v4 API deprecation warning

3. **Error Counting**
   - Total error count
   - Unique failing URLs
   - Summary every 25 errors

4. **Timing**
   - When errors occur relative to map initialization
   - Whether errors occur before/after NDVI selection

## What to Check in Browser Console

After rebuilding and running the frontend, look for:

### 1. Token Configuration (on map load)
```
🗺️ MAPBOX CONFIGURATION
  Token exists: true/false
  Token starts with 'pk.': true/false
  Token length: <number>
  Token first 20 chars: pk.eyJ1IjoiZHJhc2hp...
  Map style: mapbox://styles/mapbox/dark-v11
```

**Expected:**
- Token exists: true
- Starts with 'pk.': true
- Length: ~150-200 characters
- Style: mapbox://styles/mapbox/dark-v11

### 2. First Error Details
```
❌ Mapbox Error #1
  11. Mapbox error event: {...}
      Error message: <full error message>
      Failed URL: <complete URL>
      Extracted URL from message: https://api.mapbox.com/v4/...
      Resource type: <resource type>
      ⚠️ WARNING: v4 API is deprecated...
      Timestamp: <ISO timestamp>
```

**Key Information:**
- **Complete URL** - The full URL that's failing (not truncated)
- **Resource type** - What Mapbox is trying to load
- **v4 API warning** - If present, indicates deprecated API usage

### 3. Error Summary (after 25 errors)
```
📊 Mapbox Error Summary: 25 total errors
    Unique URLs failing: <count>
    URLs: [<array of unique URLs>]
```

### 4. Browser Network Tab

Manually check the Network tab for the failing request:
- Filter by "api.mapbox.com"
- Find the failing /v4/ requests
- Check:
  - Request Headers (Authorization header with token)
  - Response Status (401, 403, 404, 429, etc.)
  - Response body (error message from Mapbox API)

## Possible Root Causes

### A. Invalid/Expired Token (HTTP 401)
- Token is invalid or has been rotated
- Token doesn't have necessary scopes
- **Solution:** Generate new token at https://account.mapbox.com

### B. API Access Problem (HTTP 403)
- Token doesn't have permission for requested resource
- Account restrictions
- **Solution:** Check token scopes/permissions

### C. Deprecated v4 API (HTTP 404)
- The `mapbox://styles/mapbox/dark-v11` style references legacy v4 vector tiles
- Mapbox may have sunset v4 API access for this account
- **Solution:** May need to use a different style or upgrade Mapbox GL JS version

### D. Rate Limiting (HTTP 429)
- Too many requests in short time
- Free tier limits exceeded
- **Solution:** Reduce request frequency or upgrade account

### E. Network/CORS Issues
- Firewall blocking api.mapbox.com
- CORS policy rejection
- **Solution:** Check network access, proxy settings

### F. Missing Token in Requests
- Token not being passed to Mapbox API
- Environment variable not loaded
- **Solution:** Verify VITE_MAPBOX_TOKEN is set correctly

## Investigation Steps

1. **Rebuild frontend to load new diagnostics:**
   ```bash
   docker compose build client
   docker compose up -d client
   ```

2. **Open browser to http://localhost:3000**

3. **Open DevTools Console (F12)**

4. **Observe console output:**
   - Check token configuration
   - Read first 5 error details completely
   - Note the complete URL
   - Note the HTTP status from Network tab

5. **Check Browser Network Tab:**
   - Filter for "api.mapbox.com"
   - Find failing requests
   - Check Status Code
   - Check Response headers/body
   - Check Request headers (Authorization)

6. **Timing Analysis:**
   - Do errors start immediately on map load?
   - Or only after selecting NDVI?
   - This determines if it's a general Mapbox issue or NDVI-specific

## Expected Diagnosis Format

Report back with:

```
COMPLETE URL: https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/...
RESOURCE TYPE: Mapbox Vector Tile (v4 API)
HTTP STATUS: <code>
RESPONSE: <error message from API>
TOKEN PRESENT IN REQUEST: Yes/No
WHEN ERRORS OCCUR: On map load / After NDVI selection / Continuously
ERROR COUNT: <number>
UNIQUE URLS: <number>
```

## DO NOT Proceed Until Diagnosis Complete

- Do NOT regenerate token yet
- Do NOT change map style yet
- Do NOT modify NDVI code
- Do NOT assume the cause

We need the complete diagnostic output first.
