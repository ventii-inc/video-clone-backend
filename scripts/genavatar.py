#!/usr/bin/env python3
"""
Avatar Generation Script (Forked from LiveTalking)

Generates avatar data from a video file for use with Wav2Lip lip-sync.
This is a fork of LiveTalking's genavatar.py with added progress tracking.

Usage:
    # Basic usage (same as original)
    python scripts/genavatar.py --video_path video.mp4 --avatar_id my-avatar

    # With progress output (JSON to stderr)
    python scripts/genavatar.py --video_path video.mp4 --avatar_id my-avatar --progress

Progress JSON format (emitted to stderr):
    {"step": "extract_frames", "progress": 45, "current": 450, "total": 1000}
    {"step": "face_detect", "progress": 75, "current": 3, "total": 4}
    {"step": "complete", "progress": 100, "frame_count": 250}

Note: Uses pickle for coords.pkl to maintain compatibility with LiveTalking.
"""

import argparse
import json
import os
import pickle  # Required for LiveTalking compatibility
import sys
import time
from glob import glob

import cv2
import numpy as np
import torch

# Progress tracking
_progress_enabled = False


def emit_progress(step: str, progress: int, message: str = "", **extra):
    """Emit progress JSON to stderr if progress mode is enabled."""
    if not _progress_enabled:
        return
    data = {
        "step": step,
        "progress": min(100, max(0, progress)),
        "message": message,
        "timestamp": time.time(),
        **extra
    }
    print(json.dumps(data), file=sys.stderr, flush=True)


def emit_error(error: str, step: str = "error"):
    """Emit error JSON to stderr."""
    if _progress_enabled:
        data = {
            "step": step,
            "progress": -1,
            "error": error,
            "timestamp": time.time()
        }
        print(json.dumps(data), file=sys.stderr, flush=True)
    else:
        print(f"ERROR: {error}", file=sys.stderr)


def osmakedirs(path_list):
    """Create directories if they don't exist."""
    for path in path_list:
        os.makedirs(path, exist_ok=True)


def video2imgs(vid_path, save_path, ext='.png', cut_frame=10000000):
    """
    Extract frames from video file.

    Args:
        vid_path: Path to input video
        save_path: Directory to save frames
        ext: Image extension
        cut_frame: Maximum number of frames to extract
    """
    cap = cv2.VideoCapture(vid_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {vid_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    total_frames = min(total_frames, cut_frame)

    emit_progress("extract_frames", 0, f"Starting frame extraction (0/{total_frames})",
                  current=0, total=total_frames)

    count = 0
    last_progress = -1

    while True:
        if count >= cut_frame:
            break
        ret, frame = cap.read()
        if not ret:
            break

        # Add watermark
        cv2.putText(frame, "LiveTalking", (10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, (128, 128, 128), 1)
        cv2.imwrite(f"{save_path}/{count:08d}.png", frame)
        count += 1

        # Emit progress every 5% or every 10 frames
        progress = int(count / total_frames * 100) if total_frames > 0 else 0
        if progress >= last_progress + 5 or count % 10 == 0:
            emit_progress("extract_frames", progress,
                          f"Extracting frame {count}/{total_frames}",
                          current=count, total=total_frames)
            last_progress = progress

    cap.release()
    emit_progress("extract_frames", 100, f"Extracted {count} frames",
                  current=count, total=count)
    return count


def read_imgs(img_list):
    """Load images from disk into memory."""
    frames = []
    total = len(img_list)

    emit_progress("load_frames", 0, f"Loading {total} frames into memory",
                  current=0, total=total)

    for i, img_path in enumerate(img_list):
        frame = cv2.imread(img_path)
        if frame is None:
            emit_error(f"Failed to read image: {img_path}", "load_frames")
            continue
        frames.append(frame)

        # Emit progress every 10%
        if (i + 1) % max(1, total // 10) == 0 or i == total - 1:
            progress = int((i + 1) / total * 100)
            emit_progress("load_frames", progress,
                          f"Loaded {i + 1}/{total} frames",
                          current=i + 1, total=total)

    return frames


def get_smoothened_boxes(boxes, T):
    """Smooth bounding boxes over a temporal window."""
    for i in range(len(boxes)):
        if i + T > len(boxes):
            window = boxes[len(boxes) - T:]
        else:
            window = boxes[i: i + T]
        boxes[i] = np.mean(window, axis=0)
    return boxes


def face_detect(images, batch_size=16, pads=(0, 10, 0, 0), nosmooth=False, device='cuda'):
    """
    Detect faces in images.

    Args:
        images: List of images
        batch_size: Batch size for face detection
        pads: Padding (top, bottom, left, right)
        nosmooth: Disable smoothing
        device: Device to use

    Returns:
        List of (cropped_face, coords) tuples
    """
    import face_detection

    detector = face_detection.FaceAlignment(
        face_detection.LandmarksType._2D,
        flip_input=False,
        device=device
    )

    total_batches = (len(images) + batch_size - 1) // batch_size
    emit_progress("face_detect", 0, f"Starting face detection (0/{total_batches} batches)",
                  current=0, total=total_batches)

    while True:
        predictions = []
        try:
            batch_num = 0
            for i in range(0, len(images), batch_size):
                batch = np.array(images[i:i + batch_size])
                predictions.extend(detector.get_detections_for_batch(batch))
                batch_num += 1

                progress = int(batch_num / total_batches * 100)
                emit_progress("face_detect", progress,
                              f"Processing batch {batch_num}/{total_batches}",
                              current=batch_num, total=total_batches)
        except RuntimeError:
            if batch_size == 1:
                raise RuntimeError(
                    'Image too big to run face detection on GPU. '
                    'Please use the --resize_factor argument'
                )
            batch_size //= 2
            print(f'Recovering from OOM error; New batch size: {batch_size}')
            total_batches = (len(images) + batch_size - 1) // batch_size
            continue
        break

    emit_progress("face_detect", 100, "Face detection complete",
                  current=total_batches, total=total_batches)

    # Process results
    results = []
    pady1, pady2, padx1, padx2 = pads

    for rect, image in zip(predictions, images):
        if rect is None:
            # Save faulty frame for debugging
            os.makedirs('temp', exist_ok=True)
            cv2.imwrite('temp/faulty_frame.jpg', image)
            raise ValueError(
                'Face not detected! Ensure the video contains a face in all frames.'
            )

        y1 = max(0, rect[1] - pady1)
        y2 = min(image.shape[0], rect[3] + pady2)
        x1 = max(0, rect[0] - padx1)
        x2 = min(image.shape[1], rect[2] + padx2)

        results.append([x1, y1, x2, y2])

    boxes = np.array(results)
    if not nosmooth:
        boxes = get_smoothened_boxes(boxes, T=5)

    results = [
        [image[y1:y2, x1:x2], (y1, y2, x1, x2)]
        for image, (x1, y1, x2, y2) in zip(images, boxes)
    ]

    del detector
    return results


def main():
    global _progress_enabled

    parser = argparse.ArgumentParser(
        description='Generate avatar data from video for Wav2Lip lip-sync'
    )
    parser.add_argument('--img_size', default=96, type=int,
                        help='Face crop size (96 for wav2lip, 256 for wav2lip256)')
    parser.add_argument('--avatar_id', default='wav2lip_avatar1', type=str,
                        help='Unique identifier for the avatar')
    parser.add_argument('--video_path', default='', type=str, required=True,
                        help='Path to source video file')
    parser.add_argument('--output_dir', default='./data/avatars', type=str,
                        help='Base directory for avatar output')
    parser.add_argument('--nosmooth', default=False, action='store_true',
                        help='Prevent smoothing face detections')
    parser.add_argument('--pads', nargs='+', type=int, default=[0, 10, 0, 0],
                        help='Padding (top, bottom, left, right)')
    parser.add_argument('--face_det_batch_size', type=int, default=16,
                        help='Batch size for face detection')
    parser.add_argument('--max_frames', type=int, default=10000000,
                        help='Maximum frames to extract from video')
    parser.add_argument('--progress', action='store_true',
                        help='Enable JSON progress output to stderr')

    args = parser.parse_args()
    _progress_enabled = args.progress

    device = 'cuda' if torch.cuda.is_available() else 'cpu'

    if not _progress_enabled:
        print(f'Using {device} for inference.')
        print(f'Args: {args}')

    # Setup paths
    avatar_path = os.path.join(args.output_dir, args.avatar_id)
    full_imgs_path = os.path.join(avatar_path, "full_imgs")
    face_imgs_path = os.path.join(avatar_path, "face_imgs")
    coords_path = os.path.join(avatar_path, "coords.pkl")

    osmakedirs([avatar_path, full_imgs_path, face_imgs_path])

    emit_progress("init", 0, f"Starting avatar generation for {args.avatar_id}")

    try:
        # Step 1: Extract frames from video
        start_time = time.time()
        frame_count = video2imgs(args.video_path, full_imgs_path,
                                 ext='png', cut_frame=args.max_frames)

        # Step 2: Load frames
        input_img_list = sorted(glob(os.path.join(full_imgs_path, '*.[jpJP][pnPN]*[gG]')))
        frames = read_imgs(input_img_list)

        # Step 3: Detect faces
        face_det_results = face_detect(
            frames,
            batch_size=args.face_det_batch_size,
            pads=tuple(args.pads),
            nosmooth=args.nosmooth,
            device=device
        )

        # Step 4: Save cropped faces
        emit_progress("save_faces", 0, "Saving cropped faces",
                      current=0, total=len(face_det_results))

        coord_list = []
        for idx, (face, coords) in enumerate(face_det_results):
            resized_crop_frame = cv2.resize(face, (args.img_size, args.img_size))
            cv2.imwrite(f"{face_imgs_path}/{idx:08d}.png", resized_crop_frame)
            coord_list.append(coords)

            if (idx + 1) % max(1, len(face_det_results) // 10) == 0:
                progress = int((idx + 1) / len(face_det_results) * 100)
                emit_progress("save_faces", progress,
                              f"Saved {idx + 1}/{len(face_det_results)} faces",
                              current=idx + 1, total=len(face_det_results))

        emit_progress("save_faces", 100, f"Saved {len(coord_list)} faces",
                      current=len(coord_list), total=len(coord_list))

        # Step 5: Save coordinates (pickle for LiveTalking compatibility)
        emit_progress("finalize", 90, "Saving coordinates")
        with open(coords_path, 'wb') as f:
            pickle.dump(coord_list, f)

        elapsed = time.time() - start_time

        # Final result
        result = {
            "success": True,
            "avatar_id": args.avatar_id,
            "avatar_path": avatar_path,
            "frame_count": len(coord_list),
            "generation_time": round(elapsed, 2)
        }

        emit_progress("complete", 100,
                      f"Avatar generated: {len(coord_list)} frames in {elapsed:.1f}s",
                      frame_count=len(coord_list),
                      generation_time=round(elapsed, 2))

        # Output final result to stdout
        print(json.dumps(result))

    except Exception as e:
        error_msg = str(e)
        emit_error(error_msg)

        result = {
            "success": False,
            "avatar_id": args.avatar_id,
            "error": error_msg
        }
        print(json.dumps(result))
        sys.exit(1)


if __name__ == "__main__":
    main()
