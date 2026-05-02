# EC2 Auto Start/Stop — Nifty Alpha Agent

## Architecture

```
Every weekday:
08:45 IST → EventBridge wakes EC2 instance
             ↓
     EC2 boots → tmux auto-starts agent (via @reboot cron)
             ↓
     Agent runs all day (auto-restarts if it crashes)
             ↓
15:50 IST → EventBridge stops EC2 instance
```

**Instance:** `i-0619af93f882fe0d1` | **Region:** `ap-south-1`

---

## Phase 1 — AWS Console (EventBridge)

### Step 1: Create IAM execution role

1. Go to **IAM → Roles → Create role**
2. **Trusted entity type:** Custom trust policy
3. Paste:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "scheduler.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```
4. Next → attach policy: `AmazonEC2FullAccess`
5. **Role name:** `EventBridgeSchedulerEC2Role`
6. Create role

### Step 2: Create START schedule

1. Go to **EventBridge → Scheduler → Create schedule**
2. **Name:** `start-nifty-agent`
3. **Schedule type:** Recurring — Cron-based
4. **Cron:** `45 8 ? * MON-FRI *`
5. **Timezone:** `Asia/Kolkata`
6. **Flexible time window:** Off
7. Next → **Target:** AWS SDK → `ec2` → `StartInstances`
8. **Input:**
```json
{ "InstanceIds": ["i-0619af93f882fe0d1"] }
```
9. **Execution role:** Use existing → `EventBridgeSchedulerEC2Role`
10. Create schedule

### Step 3: Create STOP schedule

1. **Name:** `stop-nifty-agent`
2. **Cron:** `50 15 ? * MON-FRI *`
3. **Timezone:** `Asia/Kolkata`
4. **Flexible time window:** Off
5. **Target:** `ec2` → `StopInstances`
6. **Input:**
```json
{ "InstanceIds": ["i-0619af93f882fe0d1"] }
```
7. Same execution role. Create schedule.

> Stop at 15:50 gives 5 minutes after market close (15:45) for the agent to wrap up.

---

## Phase 2 — On EC2 (SSH in)

Start the instance manually once for this setup.

```bash
ssh -i your-key.pem ubuntu@<your-ec2-public-ip>
```

### Step 4: Create the start script

```bash
mkdir -p ~/nifty_alpha_agent/scripts ~/nifty_alpha_agent/logs

cat > ~/nifty_alpha_agent/scripts/start_agent_tmux.sh << 'EOF'
#!/usr/bin/env bash
set -e
SESSION="nifty-live"
APP_DIR="$HOME/nifty_alpha_agent"

tmux has-session -t "$SESSION" 2>/dev/null && tmux kill-session -t "$SESSION" || true

tmux new-session -d -s "$SESSION" \
  "cd $APP_DIR && source .venv/bin/activate && \
   while true; do \
     python main.py --live; \
     echo 'Agent exited — restarting in 30s...'; \
     sleep 30; \
   done"
EOF

chmod +x ~/nifty_alpha_agent/scripts/start_agent_tmux.sh
```

### Step 5: Add reboot cron

```bash
(crontab -l 2>/dev/null; echo '@reboot sleep 15 && /bin/bash /home/ubuntu/nifty_alpha_agent/scripts/start_agent_tmux.sh >> /home/ubuntu/nifty_alpha_agent/logs/reboot_start.log 2>&1') | crontab -
```

Verify:
```bash
crontab -l
```

### Step 6: Set up log rotation

```bash
sudo tee /etc/logrotate.d/nifty-agent > /dev/null << 'EOF'
/home/ubuntu/nifty_alpha_agent/logs/*.log {
    daily
    rotate 30
    compress
    missingok
    notifempty
}
EOF
```

### Step 7: Test manually

```bash
~/nifty_alpha_agent/scripts/start_agent_tmux.sh
tmux attach -t nifty-live
```

You should see the live dashboard. Detach without stopping: `Ctrl+B` then `D`

### Step 8: Stop the instance (hand off to EventBridge)

```bash
exit
```

Stop instance from AWS Console. EventBridge owns start/stop from here.

---

## Phase 3 — Verify on first market day

| Time | What to check |
|------|--------------|
| 08:47–08:50 IST | EC2 Console → instance should be `running` |
| 08:50 IST | SSH in → `tmux attach -t nifty-live` → dashboard visible |
| 15:52 IST | EC2 Console → instance should be `stopping` → `stopped` |

---

## Daily usage

| Task | Command |
|------|---------|
| View live UI | `tmux attach -t nifty-live` |
| Detach (leave running) | `Ctrl+B` then `D` |
| Check if running | `tmux ls` |
| Watch logs | `tail -f ~/nifty_alpha_agent/logs/agent.log` |
| Stop agent manually | `tmux kill-session -t nifty-live` |
| Restart agent manually | `~/nifty_alpha_agent/scripts/start_agent_tmux.sh` |
