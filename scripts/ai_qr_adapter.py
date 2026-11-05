"""Opt-in local AI QR recovery: YOLO detection + optional ONNX image SR.

No model weights are downloaded or committed. No model is allowed to invent
text; payloads come only from real QR decoding engines.
"""
import importlib
import importlib.util
import json
import os
import threading
from pathlib import Path

from ai_recovery_core import recover

CONFIG_ENV = "QR_AUDIT_AI_CONFIG"


def _existing_model(value, folder):
    if not isinstance(value,str) or not value:
        raise ValueError("AI_MODEL_PATH_REQUIRED")
    model=Path(value).expanduser()
    if not model.is_absolute():
        model=folder/model
    model=model.resolve(strict=True)
    if not model.is_file():
        raise ValueError("AI_MODEL_MUST_BE_FILE")
    return str(model)


def _number(data,key,default,min_value,max_value,integer=False):
    value=data.get(key,default)
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise ValueError(f"AI_{key.upper()}_INVALID")
    if not min_value<=value<=max_value or (integer and not isinstance(value,int)):
        raise ValueError(f"AI_{key.upper()}_OUT_OF_BOUNDS")
    return value


def read_config(path):
    file=Path(path).expanduser().resolve(strict=True)
    body=json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(body,dict) or body.get("schema_version")!="1.0":
        raise ValueError("AI_CONFIG_SCHEMA_UNSUPPORTED")
    detector=body.get("detector")
    if not isinstance(detector,dict) or detector.get("provider")!="ultralytics":
        raise ValueError("AI_DETECTOR_PROVIDER_UNSUPPORTED")
    model=_existing_model(detector.get("weights"),file.parent)
    device=detector.get("device","cpu")
    if not isinstance(device,str) or (device!="cpu" and not device.startswith("cuda:")):
        raise ValueError("AI_DEVICE_INVALID")
    settings={
        "config_file":str(file),"detector_model":model,
        "confidence":_number(detector,"confidence",.2,.01,1),
        "max_candidates":_number(detector,"max_candidates",8,1,24,True),
        "max_attempts":_number(body,"max_attempts",180,1,600,True),
        "budget_seconds":_number(body,"budget_seconds",30,1,180),
        "grid_versions":_number(body,"grid_versions",7,1,15,True),
        "device":device,
        "sr_model":None,
        "sr_scale":None,
        "zbar":body.get("zbar",True),
        "zxing":body.get("zxing",True),
    }
    for key in ("zbar","zxing"):
        if not isinstance(settings[key],bool):
            raise ValueError("AI_DECODER_OPTION_INVALID: "+key)
    sr=body.get("super_resolution")
    if sr is not None:
        if not isinstance(sr,dict) or sr.get("provider")!="onnxruntime":
            raise ValueError("AI_SR_PROVIDER_UNSUPPORTED")
        settings["sr_model"]=_existing_model(sr.get("weights"),file.parent)
        settings["sr_scale"]=_number(sr,"scale",2,2,4,True)
    return settings


def _infer_boxes(engine, image, cv2, np, settings):
    output=[]
    predictions=engine.predict(source=image,conf=settings["confidence"],
                               max_det=settings["max_candidates"],
                               device=settings["device"],verbose=False)
    for result in predictions:
        boxes=getattr(result,"boxes",None)
        if boxes is None:
            continue
        coords=boxes.xyxy.cpu().numpy()
        confidences=boxes.conf.cpu().numpy()
        masks=getattr(result,"masks",None)
        polygons=getattr(masks,"xy",[]) if masks is not None else []
        for index,box in enumerate(coords):
            polygon=polygons[index] if index<len(polygons) else None
            output.append({"bbox":[float(v) for v in box],
                           "confidence":float(confidences[index]),
                           "polygon":polygon})
    return output


def _super_resolve(session, image, cv2, np, expected_scale):
    """Strict contract: RGB NCHW float32 [0,1] => RGB NCHW [0,1].

    Other ONNX super-resolution models need their own adapter; do not silently
    reshape arbitrary models or fabricate missing data.
    """
    h,w=image.shape[:2]
    if h*w*expected_scale**2>8_000_000:
        return None
    if h<8 or w<8:
        return None
    rgb=cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
    tensor=np.ascontiguousarray(rgb.transpose(2,0,1)[None].astype(np.float32)/255.)
    output=session.run(None,{session.get_inputs()[0].name:tensor})[0]
    expected=(1,3,h*expected_scale,w*expected_scale)
    if output.shape!=expected or not np.all(np.isfinite(output)):
        raise ValueError("AI_SR_OUTPUT_CONTRACT_MISMATCH")
    if np.min(output)<-.01 or np.max(output)>1.01:
        raise ValueError("AI_SR_NORMALIZATION_MISMATCH")
    result=(np.clip(output[0].transpose(1,2,0),0,1)*255).round().astype(np.uint8)
    return cv2.cvtColor(result,cv2.COLOR_RGB2BGR)


def register_qr_audit(strategies,decoders,context):
    path=context.get("ai_config_path") or os.environ.get(CONFIG_ENV)
    if not path:
        raise ValueError(f"AI_CONFIG_REQUIRED: set {CONFIG_ENV} to an existing local JSON file")
    config=read_config(path)
    cv2,np=context.get("cv2"),context.get("numpy")
    if cv2 is None or np is None:
        raise RuntimeError("AI_REQUIRES_OPENCV_NUMPY")
    if importlib.util.find_spec("ultralytics") is None:
        raise RuntimeError("AI_REQUIRES_ULTRALYTICS_INSTALLED")
    if config["sr_model"] and importlib.util.find_spec("onnxruntime") is None:
        raise RuntimeError("AI_REQUIRES_ONNXRUNTIME_INSTALLED")
    context.setdefault("source_files",[]).extend(
        [config["config_file"],config["detector_model"]]+
        ([config["sr_model"]] if config["sr_model"] else [])
    )
    context.setdefault("dependencies",[]).append({
        "name":"ai-qr-local-yolo","version":"experimental-v2",
        "config_file":config["config_file"],
        "model_provider":"ultralytics",
        "optional_sr":bool(config["sr_model"]),
    })
    worker_state=threading.local()

    def _state():
        if not hasattr(worker_state,"model"):
            library=importlib.import_module("ultralytics")
            worker_state.model=library.YOLO(config["detector_model"])
        if config["sr_model"] and not hasattr(worker_state,"sr"):
            runtime=importlib.import_module("onnxruntime")
            worker_state.sr=runtime.InferenceSession(
                config["sr_model"],providers=["CPUExecutionProvider"]
            )
        return worker_state

    # Validate that model weights and architecture are actually loadable
    # before creating a new report. Prevent a whole run of fake ERROR attempts.
    try:
        _state()
    except Exception as exc:
        raise RuntimeError("AI_LOCAL_MODEL_LOAD_FAILED: " + type(exc).__name__) from exc

    def decode(image,decoder_context,options):
        current=_state()
        detections=_infer_boxes(current.model,image,cv2,np,config)
        try:
            zxing=importlib.import_module("zxingcpp") if config["zxing"] else None
        except ImportError:
            zxing=None
        try:
            zbar=importlib.import_module("pyzbar.pyzbar").decode if config["zbar"] else None
        except (ImportError,OSError):
            zbar=None
        sr=(lambda patch:_super_resolve(current.sr,patch,cv2,np,config["sr_scale"])
            ) if config["sr_model"] else None
        return recover(
            image,detections,cv2,np,zxing=zxing,zbar=zbar,
            super_resolve=sr,max_candidates=config["max_candidates"],
            max_attempts=config["max_attempts"],grid_versions=config["grid_versions"],
            budget_seconds=config["budget_seconds"],
        )

    strategies.register("A01",lambda image,ctx,params:image,
                        version="ai-original-1",
                        parameters={"operation":"identity","ai_detector":"local-yolo"})
    decoders.register("ai",decode,version="ai-local-multi-engine-v1",
                      options={"model_provider":"ultralytics","sr_enabled":bool(config["sr_model"]),
                               "max_candidates":config["max_candidates"],
                               "max_attempts":config["max_attempts"],
                               "grid_versions":config["grid_versions"],
                               "source":"local-model-only"})
