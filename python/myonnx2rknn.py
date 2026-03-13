import os
import urllib
import traceback
import time
import sys
import numpy as np
import cv2
from rknn.api import RKNN
from math import exp

ONNX_MODEL = '/home/cat/python_docs/lubancat_ai_manual_code/example/yolo11-myfish/model/myfish_rect.onnx'
RKNN_MODEL = '/home/cat/python_docs/lubancat_ai_manual_code/example/yolo11-myfish/model/myfish_rect.rknn'
DATASET = '/home/cat/python_docs/lubancat_ai_manual_code/example/myfish_Dataset/myfish_subset_20.txt'

QUANTIZE_ON = False

CLASSES = ['myfish']

meshgrid = []

class_num = len(CLASSES)
headNum = 3
strides = [8, 16, 32]
mapSize = [[80, 80], [40, 40], [20, 20]]
nmsThresh = 0.5
objectThresh = 0.5

input_imgH = 640
input_imgW = 640


class DetectBox:
    def __init__(self, classId, score, xmin, ymin, xmax, ymax):
        self.classId = classId
        self.score = score
        self.xmin = xmin
        self.ymin = ymin
        self.xmax = xmax
        self.ymax = ymax

def GenerateMeshgrid():
    for index in range(headNum):
        for i in range(mapSize[index][0]):
            for j in range(mapSize[index][1]):
                meshgrid.append(j + 0.5)
                meshgrid.append(i + 0.5)


def IOU(xmin1, ymin1, xmax1, ymax1, xmin2, ymin2, xmax2, ymax2):
    xmin = max(xmin1, xmin2)
    ymin = max(ymin1, ymin2)
    xmax = min(xmax1, xmax2)
    ymax = min(ymax1, ymax2)

    innerWidth = xmax - xmin
    innerHeight = ymax - ymin

    innerWidth = innerWidth if innerWidth > 0 else 0
    innerHeight = innerHeight if innerHeight > 0 else 0

    innerArea = innerWidth * innerHeight

    area1 = (xmax1 - xmin1) * (ymax1 - ymin1)
    area2 = (xmax2 - xmin2) * (ymax2 - ymin2)

    total = area1 + area2 - innerArea

    return innerArea / total


def NMS(detectResult):
    predBoxs = []

    sort_detectboxs = sorted(detectResult, key=lambda x: x.score, reverse=True)

    for i in range(len(sort_detectboxs)):
        xmin1 = sort_detectboxs[i].xmin
        ymin1 = sort_detectboxs[i].ymin
        xmax1 = sort_detectboxs[i].xmax
        ymax1 = sort_detectboxs[i].ymax
        classId = sort_detectboxs[i].classId

        if sort_detectboxs[i].classId != -1:
            predBoxs.append(sort_detectboxs[i])
            for j in range(i + 1, len(sort_detectboxs), 1):
                if classId == sort_detectboxs[j].classId:
                    xmin2 = sort_detectboxs[j].xmin
                    ymin2 = sort_detectboxs[j].ymin
                    xmax2 = sort_detectboxs[j].xmax
                    ymax2 = sort_detectboxs[j].ymax
                    iou = IOU(xmin1, ymin1, xmax1, ymax1, xmin2, ymin2, xmax2, ymax2)
                    if iou > nmsThresh:
                        sort_detectboxs[j].classId = -1
    return predBoxs


def sigmoid(x):
    return 1 / (1 + exp(-x))


def postprocess_v8(output, img_h, img_w):
    print('postprocess for YOLOv8/v11 single output...')
    
    # output shape: [1, 5+num_classes, 8400] 或类似
    print('Output shape:', output.shape)
    
    # 转置和重塑输出
    output = output[0]  # 去掉batch维度
    print('Output after removing batch:', output.shape)
    
    # 对于YOLOv8/v11，输出通常是 [5+num_classes, 8400]
    # 前4个是bbox (cx, cy, w, h)，第5个是obj_score，后面是class_scores
    num_classes = output.shape[0] - 5
    print('Number of classes:', num_classes)
    
    # 将输出拆分为不同的部分
    bbox_data = output[:4]  # [4, 8400]
    obj_scores = output[4:5]  # [1, 8400] 
    cls_scores = output[5:]   # [num_classes, 8400]
    
    # 计算最终得分
    scores = obj_scores * cls_scores  # [num_classes, 8400]
    
    detectResult = []
    
    # 遍历所有8400个预测
    for i in range(scores.shape[1]):
        # 找到最大得分和对应的类别
        max_score = np.max(scores[:, i])
        class_id = np.argmax(scores[:, i])
        
        if max_score > objectThresh:
            # 获取边界框
            cx, cy, w, h = bbox_data[:, i]
            
            # 转换为绝对坐标
            xmin = (cx - w/2) * img_w
            ymin = (cy - h/2) * img_h
            xmax = (cx + w/2) * img_w
            ymax = (cy + h/2) * img_h
            
            # 确保坐标在图像范围内
            xmin = max(0, xmin)
            ymin = max(0, ymin)
            xmax = min(img_w, xmax)
            ymax = min(img_h, ymax)
            
            box = DetectBox(class_id, max_score, xmin, ymin, xmax, ymax)
            detectResult.append(box)
    
    print('detectResult:', len(detectResult))
    predBox = NMS(detectResult)
    return predBox


def export_rknn_inference(img):
    # Create RKNN object
    rknn = RKNN(verbose=False)

    # pre-process config
    print('--> Config model')
    rknn.config(mean_values=[[0, 0, 0]], std_values=[[255, 255, 255]], 
                quantized_algorithm='normal', quantized_method='channel', 
                target_platform='rk3576')
    print('done')

    # Load ONNX model - 修复：去掉outputs参数
    print('--> Loading model')
    ret = rknn.load_onnx(model=ONNX_MODEL)  # 自动识别输出节点
    if ret != 0:
        print('Load model failed!')
        exit(ret)
    print('done')

    # Build model
    print('--> Building model')
    ret = rknn.build(do_quantization=QUANTIZE_ON, dataset=DATASET, rknn_batch_size=1)
    if ret != 0:
        print('Build model failed!')
        exit(ret)
    print('done')

    # Export RKNN model
    print('--> Export rknn model')
    ret = rknn.export_rknn(RKNN_MODEL)
    if ret != 0:
        print('Export rknn model failed!')
        exit(ret)
    print('done')

    # Init runtime environment
    print('--> Init runtime environment')
    ret = rknn.init_runtime()
    if ret != 0:
        print('Init runtime environment failed!')
        exit(ret)
    print('done')

    # Inference
    print('--> Running model')
    outputs = rknn.inference(inputs=[img])
    rknn.release()
    print('done')

    return outputs


if __name__ == '__main__':
    print('This is main ...')
    # 注意：单输出模型不需要 GenerateMeshgrid()

    img_path = '/home/cat/python_docs/lubancat_ai_manual_code/example/yolo11-myfish/model/image00500.png'
    orig_img = cv2.imread(img_path)
    img_h, img_w = orig_img.shape[:2]
    
    origimg = cv2.resize(orig_img, (input_imgW, input_imgH), interpolation=cv2.INTER_LINEAR)
    origimg = cv2.cvtColor(origimg, cv2.COLOR_BGR2RGB)
    
    img = np.expand_dims(origimg, 0)

    outputs = export_rknn_inference(img)

    # 对于单输出模型，outputs只有一个元素
    print('Number of outputs:', len(outputs))
    for i, out in enumerate(outputs):
        print(f'Output {i} shape: {out.shape}')

    # 使用新的后处理函数
    predbox = postprocess_v8(outputs[0], img_h, img_w)

    print('Detected objects:', len(predbox))

    # 绘制结果（保持不变）
    for i in range(len(predbox)):
        xmin = int(predbox[i].xmin)
        ymin = int(predbox[i].ymin)
        xmax = int(predbox[i].xmax)
        ymax = int(predbox[i].ymax)
        classId = predbox[i].classId
        score = predbox[i].score

        cv2.rectangle(orig_img, (xmin, ymin), (xmax, ymax), (0, 255, 0), 2)
        ptext = (xmin, ymin)
        title = CLASSES[classId] + ":%.2f" % (score)
        cv2.putText(orig_img, title, ptext, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)

    cv2.imwrite('./test_rknn_result.jpg', orig_img)
    cv2.imshow("test", orig_img)  # 注意：这里应该是orig_img而不是origimg
    cv2.waitKey(0)