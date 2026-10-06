# Face models

Used by `ReferenceFrameSelectionService` (picking a character's reference frame)
and, later, the optional face-similarity check. Both run locally through OpenCV;
nothing is sent anywhere.

Source: OpenCV Zoo, https://github.com/opencv/opencv_zoo

| File | Model | Licence |
|---|---|---|
| `face_detection_yunet_2023mar.onnx` | YuNet face detector (about 0.2 MB) - committed to the repo | MIT |
| `face_recognition_sface_2021dec.onnx` | SFace face recognition (about 37 MB) - NOT committed (git-ignored); not used yet - to be fetched when the similarity check is built | Apache-2.0 |

## YuNet - MIT License

Copyright (c) 2020 Shiqi Yu <shiqi.yu@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in the
Software without restriction, including without limitation the rights to use,
copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the
Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN
AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## SFace - Apache License 2.0

The model is distributed under the Apache License, Version 2.0
(http://www.apache.org/licenses/LICENSE-2.0) by the OpenCV Zoo project. The full
text is published at
https://github.com/opencv/opencv_zoo/blob/main/models/face_recognition_sface/LICENSE
