"""
Notification Manager for Sentinel.

Handles sending alerts to external services (Discord/Slack) via Webhooks.
Includes cooldown logic to prevent spamming the user.
"""
import time
import requests
import threading
import logging
from typing import Dict

logger = logging.getLogger("notifications")

class NotificationManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(NotificationManager, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self):
        if self.initialized:
            return
            
        self.webhook_url = None
        self.enabled = False
        self.cooldown_seconds = 60
        
        # Track last alert time per label
        # Format: { "person": timestamp, "car": timestamp }
        self.last_alerts: Dict[str, float] = {}
        self.initialized = True

    def configure(self, config: dict):
        """Loads configuration from the manifest dictionary."""
        notif_cfg = config.get('notifications', {})
        self.enabled = notif_cfg.get('enabled', False)
        self.webhook_url = notif_cfg.get('webhook_url', '')
        self.cooldown_seconds = notif_cfg.get('cooldown_seconds', 60)
        
        if self.enabled and not self.webhook_url:
            logger.warning("Notifications enabled but no Webhook URL provided.")
            self.enabled = False

    def send_alert(self, label: str, confidence: float, camera_id: str, frame=None):
        """
        Triggers an alert if cooldown has passed.
        Runs asynchronously to avoid blocking the main thread.
        """
        if not self.enabled or not self.webhook_url:
            return

        now = time.time()
        last_time = self.last_alerts.get(label, 0)
        
        if now - last_time < self.cooldown_seconds:
            return  # Cooldown active
            
        # Update timestamp
        self.last_alerts[label] = now
        
        # Encode image if provided
        image_bytes = None
        if frame is not None:
             try:
                 import cv2
                 # Resize for speed/size if large? Optional.
                 _, buffer = cv2.imencode('.jpg', frame)
                 image_bytes = buffer.tobytes()
             except Exception as e:
                 logger.error(f"Failed to encode alarm image: {e}")

        # Fire and forget
        info = {
            "label": label,
            "conf": f"{confidence:.2f}",
            "cam": camera_id,
            "url": self.webhook_url,
            "image": image_bytes
        }
        threading.Thread(target=self._post_webhook, args=(info,), daemon=True).start()

    def _post_webhook(self, info: dict):
        """Worker function to send the POST request."""
        try:
            import json
            
            # Base content
            content_str = f"🚨 **Sentinel Alert** \nDetected **{info['label']}** ({info['conf']}) on Camera **{info['cam']}**"
            
            if info.get('image') and "discord" in info['url']:
                # Multipart upload for Discord
                files = {
                    'file': ('snapshot.jpg', info['image'], 'image/jpeg')
                }
                payload = {
                    "content": content_str,
                    "embeds": [{
                        "image": {
                            "url": "attachment://snapshot.jpg"
                        }
                    }]
                }
                requests.post(info['url'], data={'payload_json': json.dumps(payload)}, files=files, timeout=10)
            else:
                # Standard JSON payload (Slack or Discord Text-Only)
                payload = {
                    "content": content_str,
                    "text": content_str
                }
                requests.post(info['url'], json=payload, timeout=5)
                
            logger.info(f"Sent notification for {info['label']}")
            
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")

# Global singleton
notification_manager = NotificationManager()
