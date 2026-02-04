import yaml
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any
import os

logger = logging.getLogger("asset_manager")

@dataclass
class CameraAsset:
    id: str
    ip: str
    lat: float
    lon: float
    heading: int
    fov: int
    tags: List[str]
    status: str = "OFFLINE"
    detection_count: int = 0
    
    # Store dynamic state
    last_seen: float = 0.0

class AssetManager:
    def __init__(self, manifest_path="config/site_manifest.yaml"):
        self.assets: Dict[str, CameraAsset] = {}
        # Ensure path is absolute or correct relative to execution
        if not os.path.exists(manifest_path):
            # Try finding it relative to project root if run from module
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
            candidate = os.path.join(project_root, manifest_path)
            if os.path.exists(candidate):
                manifest_path = candidate
            else:
                logger.warning(f"Manifest not found at {manifest_path} or {candidate}")
        
        self.manifest_path = manifest_path
        self.load_manifest()

    def load_manifest(self):
        try:
            with open(self.manifest_path, 'r') as f:
                data = yaml.safe_load(f)
                
                self.center_coordinates = data.get('center_coordinates', [30.2672, -97.7431])
                self.site_name = data.get('site_name', 'UNKNOWN_SITE')
                
                for item in data.get('assets', []):
                    # Parse YAML into Python Objects
                    # Map 'spatial' dict to flat attributes
                    spatial = item.get('spatial', {})
                    conn = item.get('connection', {})
                    
                    self.assets[item['id']] = CameraAsset(
                        id=item['id'],
                        ip=conn.get('ip', '0.0.0.0'),
                        lat=spatial.get('lat', 0.0),
                        lon=spatial.get('lon', 0.0),
                        heading=spatial.get('heading', 0),
                        fov=spatial.get('fov', 60),
                        tags=item.get('tags', [])
                    )
            logger.info(f"Loaded {len(self.assets)} assets from {self.manifest_path}")
        except Exception as e:
            logger.error(f"Failed to load manifest: {e}")

    def update_status(self, camera_id: str, is_online: bool):
        """Update the connectivity status of a camera."""
        # Map integer IDs (0) to string IDs for now, or handle mapping
        # In this demo, '0' or 0 maps to 'CAM_01_NORTH_GATE' for simulation
        
        target_id = None
        if str(camera_id) == '0':
            target_id = 'CAM_01_NORTH_GATE'
        elif camera_id in self.assets:
            target_id = camera_id
            
        if target_id and target_id in self.assets:
            self.assets[target_id].status = "ONLINE" if is_online else "OFFLINE"

    def update_detections(self, camera_id: str, count: int):
        """Update the detection count for a camera."""
        target_id = None
        if str(camera_id) == '0':
            target_id = 'CAM_01_NORTH_GATE'
        elif camera_id in self.assets:
            target_id = camera_id
            
        if target_id and target_id in self.assets:
            self.assets[target_id].detection_count = count

    def get_geojson(self):
        """
        Convert internal assets to GeoJSON format for the frontend map.
        This allows the map to render everything instantly.
        """
        features = []
        for cam in self.assets.values():
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [cam.lon, cam.lat]
                },
                "properties": {
                    "id": cam.id,
                    "heading": cam.heading,
                    "fov": cam.fov,
                    "range": 50, # hardcode or from config
                    "detections": cam.detection_count,
                    "status": cam.status,
                    "tags": cam.tags
                }
            })
        return {"type": "FeatureCollection", "features": features}

# Singleton instance for easy import
asset_manager = AssetManager()
