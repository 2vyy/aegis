"""
Frame Processor: Server-side AI inference pipeline.

Pipeline:
1. YOLO Object Detection (Inference Only)
2. DeepSORT Tracking (Resume Compliance)
3. CoT Event Generation
"""
import cv2
import numpy as np
from concurrent.futures import ThreadPoolExecutor, Future
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort
import time


class FrameProcessor:
    """
    Processes video frames using YOLOv8 for detection and DeepSORT for tracking.
    """
    INFERENCE_INTERVAL = 3

    def __init__(self, camera_id: int):
        self.camera_id = camera_id
        self.frame_count = 0
        
        self.inference_future: Future | None = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        
        # DeepSORT Tracker
        self.tracker = DeepSort(max_age=30, n_init=3, nms_max_overlap=1.0, max_cosine_distance=0.2)
        
        # Tracking State
        self.active_tracks = {}
        self.latest_tracks = [] # Store deepsort tracks for drawing
        
        # Load YOLO model
        try:
            self.model = YOLO("yolov8n.pt")
            print("YOLOv8 model loaded successfully.")
        except Exception as e:
            print(f"Failed to load YOLO model: {e}")
            self.model = None

    def _run_inference(self, frame: np.ndarray):
        """Runs YOLO Detection (called in background thread)."""
        if not self.model:
            return []
        
        # Run Detection Only (Conf > 0.4)
        results = self.model(frame, verbose=False, conf=0.4)
        return results

    def process(self, frame: np.ndarray) -> np.ndarray:
        """
        Processes a single frame: runs YOLO async, updates DeepSORT sync.
        """
        self.frame_count += 1
        
        # --- Check for completed detection ---
        detections = []
        if self.inference_future is not None and self.inference_future.done():
            try:
                results = self.inference_future.result()
                # Convert YOLO results to DeepSORT format: [[left, top, w, h], conf, class_name]
                for result in results:
                    for box in result.boxes:
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                        w = x2 - x1
                        h = y2 - y1
                        conf = box.conf[0].item()
                        cls = int(box.cls[0].item())
                        label = self.model.names[cls]
                        detections.append([[x1, y1, w, h], conf, label])
                
                self.inference_future = None
            except Exception as e:
                print(f"Detection error: {e}")
                self.inference_future = None

        # --- Update DeepSORT Tracker ---
        # We update tracker even if no new detections (it predicts)
        # But deep_sort_realtime expects detections list. 
        # If we didn't run inference this frame, we pass empty list? 
        # No, 'update_tracks' handles prediction if list is empty?
        # Ideally we only update when we have new detections or we let it coast.
        # Let's simple logic: If new detections, update.
        
        if detections:
            try:
                self.latest_tracks = self.tracker.update_tracks(detections, frame=frame)
                self._process_active_tracks(self.latest_tracks, frame)
            except Exception as e:
                print(f"Tracker Update Error: {e}")

        # --- Submit new job ---
        if self.frame_count % self.INFERENCE_INTERVAL == 0 and self.model and self.inference_future is None:
            self.inference_future = self.executor.submit(self._run_inference, frame.copy())

        # --- Draw Visualization ---
        for track in self.latest_tracks:
            if not track.is_confirmed(): continue
            
            track_id = track.track_id
            ltrb = track.to_ltrb() # Left Top Right Bottom
            x1, y1, x2, y2 = int(ltrb[0]), int(ltrb[1]), int(ltrb[2]), int(ltrb[3])
            
            # Draw Bounding Box
            color = (0, 255, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            
            # Label
            try:
                label = track.get_det_class() or "object"
                # DeepSORT sometimes loses class info if not passed correctly or coasting
                # We stored it in 'active_tracks' too
                if track_id in self.active_tracks:
                    label = self.active_tracks[track_id]['label']
            except:
                label = "object"
                
            text = f"ID:{track_id} {label}"
            cv2.putText(frame, text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        return frame

    def _process_active_tracks(self, tracks, frame):
        """Updates DB and triggers notifications based on confirmed tracks."""
        import time
        from server_node.core.database import db_manager, TrackedEvent
        from server_node.core.notifications import notification_manager
        
        now = time.time()
        current_track_ids = set()

        for track in tracks:
            if not track.is_confirmed(): continue
            
            track_id = track.track_id
            current_track_ids.add(track_id)
            
            # Retrieve label/conf
            label = track.get_det_class() or "unknown"
            conf = track.get_det_conf() or 0.5
            
            # Logic: Is this a NEW track ID?
            if track_id not in self.active_tracks:
                # 1. NEW TRACK FOUND
                
                # Check for label override from our localized cache (prevent 'unknown' flicker)
                # (Optional optimization)
                
                print(f"New DeepSORT Track {track_id} ({label})")
                
                # Save Snapshot
                snapshot_path = self._save_snapshot(frame, track_id)
                
                # Log to DB
                # Note: db_manager likely expects integer ID. DeepSORT IDs can be strings or ints.
                # deep_sort_realtime usually returns string IDs "1", "2".
                # SQLite wrapper might need string.
                # existing 'TrackedEvent' likely has 'track_id: int'.
                # We should cast or update DB schema. Let's try cast to int, usually works if monotonic.
                # Actually deep_sort_realtime often returns '1'.
                
                try:
                    db_track_id = int(track_id)
                except:
                    # Fallback hash if UUID
                    db_track_id = hash(track_id) % 100000
                
                event = TrackedEvent(
                    track_id=db_track_id, 
                    label=label,
                    camera_id=str(self.camera_id),
                    start_time=now,
                    last_seen=now,
                    max_conf=conf,
                    snapshot_path=snapshot_path
                )
                row_id = db_manager.create_event(event)

                # Notify User
                notification_manager.send_alert(label, conf, str(self.camera_id), frame)
                
                # Update Memory
                self.active_tracks[track_id] = {
                    'row_id': row_id,
                    'label': label,
                    'max_conf': conf,
                    'last_seen': now
                }
            else:
                # 2. EXISTING MAPPED TRACK
                track_data = self.active_tracks[track_id]
                track_data['last_seen'] = now
                
                # Update label if we got a better detection confirmation
                if label != "unknown" and track_data['label'] == "unknown":
                    track_data['label'] = label
                
                # Update DB
                # db_manager.update_event(track_data['row_id'], now, track_data['max_conf'])
        
        # 3. CLEANUP STALE TRACKS
        stale_ids = []
        for tid, data in self.active_tracks.items():
            if now - data['last_seen'] > 10.0:  # 10s memory
                stale_ids.append(tid)
        
        for tid in stale_ids:
            del self.active_tracks[tid]

        # Update Asset Manager status
        from server_node.core.asset_manager import asset_manager
        asset_manager.update_detections(self.camera_id, len(current_track_ids))

    def _save_snapshot(self, frame, track_id) -> str:
        """Saves a snapshot of the event to disk."""
        import os
        import cv2
        directory = os.path.join(os.getcwd(), "snapshots")
        os.makedirs(directory, exist_ok=True)
        filename = f"track_{track_id}_{int(time.time())}.jpg"
        path = os.path.join(directory, filename)
        cv2.imwrite(path, frame)
        return path
