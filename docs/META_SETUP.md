# 🎛️ Meta WhatsApp Webhook Setup Guide

### 1. Webhook URL Configuration
In the Meta Developer Portal (**WhatsApp > Configuration**), use the following:

- **Callback URL:** `https://<YOUR_NGROK_ID>.ngrok-free.app/webhook/whatsapp`
- **Verify Token:** (Check your `.env` file for `WHATSAPP_VERIFY_TOKEN`)
- **Default Value:** `kisanmitra_verify_2025`

### 2. Webhook Fields (Subscription)
After successfully verifying the Callback URL, click **Manage** and subscribe to the following field:

- [x] **messages** (Essential for receiving farmer texts)

### 3. Monitoring Connection
To retrieve your active Ngrok URL from the Docker container, run:
```bash
curl -s http://localhost:4040/api/tunnels | jq -r '.tunnels[0].public_url'
```

### 4. Required Secrets Checklist
Ensure these are updated in your `.env` before cutover:
- [ ] `WHATSAPP_TOKEN` (Permanent Access Token)
- [ ] `WHATSAPP_PHONE_NUMBER_ID`
- [ ] `WHATSAPP_APP_SECRET` (For HMAC validation)
