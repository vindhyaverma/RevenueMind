import logging
import json
from datetime import datetime

class StructuredFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "event_type": record.msg,
        }
        
        # Add all extra attributes
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)
            
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_data)

def get_logger(name: str):
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
    return logger

class StructuredLogger:
    def __init__(self, name: str):
        self.logger = get_logger(name)
        
    def info(self, event_type: str, **kwargs):
        self.logger.info(event_type, extra={"extra_data": kwargs})
        
    def error(self, event_type: str, **kwargs):
        self.logger.error(event_type, extra={"extra_data": kwargs})
        
    def warning(self, event_type: str, **kwargs):
        self.logger.warning(event_type, extra={"extra_data": kwargs})
