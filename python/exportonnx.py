import ultralytics

model = ultralytics.YOLO("/home/cat/python_docs/lubancat_ai_manual_code/example/yolo11-myfish/model/myfish_rect.pt")  # load a pretrained model (recommended for training)

model.export(format="onnx")  # export the model to ONNX format
