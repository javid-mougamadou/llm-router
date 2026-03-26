#!/usr/bin/env bash
# LLM Router — Usage Examples
# Adjust BASE_URL and ADMIN_KEY as needed.

BASE_URL="http://localhost:4000"
ADMIN_KEY="sk-admin-secret"

echo "=== Health check ==="
curl -s "$BASE_URL/health"
echo

echo ""
echo "=== Create a user (monthly: \$5, daily: \$1) ==="
curl -s "$BASE_URL/admin/users" \
  -H "x-api-key: $ADMIN_KEY" \
  -H "content-type: application/json" \
  -d '{"name": "alice", "monthly_budget": 5.0, "daily_budget": 1.0}'
echo

echo ""
echo "=== List users ==="
curl -s "$BASE_URL/admin/users" \
  -H "x-api-key: $ADMIN_KEY" | python3 -m json.tool
echo

echo ""
echo "=== List user keys ==="
curl -s "$BASE_URL/admin/users/1/keys" \
  -H "x-api-key: $ADMIN_KEY" | python3 -m json.tool
echo

echo ""
echo "=== List models ==="
curl -s "$BASE_URL/v1/models" \
  -H "x-api-key: $ADMIN_KEY" | python3 -m json.tool
echo

echo ""
echo "--- Anthropic API (non-streaming) ---"
echo "Replace USER_KEY with the key returned by create user."
echo ""
echo 'curl -s "$BASE_URL/v1/messages" \'
echo '  -H "x-api-key: USER_KEY" \'
echo '  -H "content-type: application/json" \'
echo '  -d '"'"'{"model":"claude-haiku-4-5-20251001","max_tokens":50,"messages":[{"role":"user","content":"Hi"}]}'"'"

echo ""
echo "--- OpenAI API (non-streaming) ---"
echo ""
echo 'curl -s "$BASE_URL/v1/chat/completions" \'
echo '  -H "Authorization: Bearer USER_KEY" \'
echo '  -H "content-type: application/json" \'
echo '  -d '"'"'{"model":"claude-haiku-4-5-20251001","max_tokens":50,"messages":[{"role":"user","content":"Hi"}]}'"'"

echo ""
echo "--- Streaming (Anthropic) ---"
echo ""
echo 'curl -sN "$BASE_URL/v1/messages" \'
echo '  -H "x-api-key: USER_KEY" \'
echo '  -H "content-type: application/json" \'
echo '  -d '"'"'{"model":"claude-haiku-4-5-20251001","max_tokens":50,"stream":true,"messages":[{"role":"user","content":"Hi"}]}'"'"

echo ""
echo "=== Usage summary ==="
curl -s "$BASE_URL/admin/usage" \
  -H "x-api-key: $ADMIN_KEY" | python3 -m json.tool
echo

echo ""
echo "=== Update monthly budget ==="
echo 'curl -s "$BASE_URL/admin/users/1" -X PATCH \'
echo '  -H "x-api-key: $ADMIN_KEY" \'
echo '  -H "content-type: application/json" \'
echo '  -d '"'"'{"monthly_budget": 10.0}'"'"

echo ""
echo "=== Reset monthly spend ==="
echo 'curl -s "$BASE_URL/admin/users/1" -X PATCH \'
echo '  -H "x-api-key: $ADMIN_KEY" \'
echo '  -H "content-type: application/json" \'
echo '  -d '"'"'{"reset_spend": true}'"'"

echo ""
echo "=== Toggle key active/inactive ==="
echo 'curl -s "$BASE_URL/admin/keys/sk-xxx" -X PATCH \'
echo '  -H "x-api-key: $ADMIN_KEY" \'
echo '  -H "content-type: application/json" \'
echo '  -d '"'"'{"active": false}'"'"

echo ""
echo "=== Delete a key ==="
echo 'curl -s "$BASE_URL/admin/keys/sk-xxx" -X DELETE \'
echo '  -H "x-api-key: $ADMIN_KEY"'

echo ""
echo "=== User login (returns JWT) ==="
echo 'curl -s "$BASE_URL/user/login" \'
echo '  -H "content-type: application/json" \'
echo '  -d '"'"'{"username": "alice", "password": "changeme"}'"'"

echo ""
echo "=== Dashboards ==="
echo "Admin: $BASE_URL/admin-ui"
echo "User:  $BASE_URL/user-ui"
