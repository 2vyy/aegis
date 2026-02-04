
import datetime
import uuid

class CoTGenerator:
    """
    Generates Cursor-on-Target (CoT) XML messages.
    """
    
    @staticmethod
    def generate_xml(uid, type_str, lat, lon, label, confidence):
        """
        Generates a basic CoT event XML string.
        """
        now = datetime.datetime.utcnow()
        time_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        stale_str = (now + datetime.timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # Basic CoT schema
        xml = f"""
<event version="2.0" uid="{uid}" type="{type_str}" time="{time_str}" start="{time_str}" stale="{stale_str}" how="m-g">
    <point lat="{lat}" lon="{lon}" hae="0" ce="10" le="10"/>
    <detail>
        <contact callsign="{label}"/>
        <remarks>Detected {label} with confidence {confidence:.2f}</remarks>
    </detail>
</event>
"""
        return xml.strip()

    @staticmethod
    def generate_detection_event(label, confidence):
        """
        Helper for object detections. Generates a new UID for each detection 
        (or could track existing ones if we had a tracker).
        """
        # Mapping generic YOLO classes to CoT types could go here.
        # For now, we use a generic atom type.
        cot_type = "a-u-G" 
        if label == "person":
             cot_type = "a-h-G" # hostile/ground? or just human
            
        # Dummy coordinates since we don't have GPS
        lat = "34.0522" 
        lon = "-118.2437"
        
        return CoTGenerator.generate_xml(uuid.uuid4(), cot_type, lat, lon, label, confidence)
