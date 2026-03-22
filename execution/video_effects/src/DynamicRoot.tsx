import React from "react";
import {
  Composition,
  AbsoluteFill,
  Img,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
  staticFile,
} from "remotion";

// This file is dynamically overwritten by pan_3d_transition.py
// with the correct frame count, dimensions, and effect parameters.
// The version below is a placeholder for development/studio use.

const VideoTransition3D: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const frameCount = 300;
  const swivelStart = 3.5;
  const swivelEnd = -3.5;
  const tiltStart = 1.7;
  const tiltEnd = 1.7;
  const perspectiveVal = 1000;

  const sourceFrameIndex = Math.min(Math.floor(frame), frameCount - 1);

  const progress = interpolate(frame, [0, durationInFrames], [0, 1], {
    extrapolateRight: "clamp",
  });

  const swivelDeg = interpolate(progress, [0, 1], [swivelStart, swivelEnd]);
  const tiltDeg = interpolate(progress, [0, 1], [tiltStart, tiltEnd]);
  const scaleVal = 0.985;

  const frameNum = String(sourceFrameIndex + 1).padStart(4, "0");
  const frameFilename = "frame_" + frameNum + ".jpg";

  return (
    <AbsoluteFill
      style={{
        perspective: perspectiveVal + "px",
        backgroundColor: "#2d3436",
      }}
    >
      <AbsoluteFill
        style={{
          transform: `rotateY(${swivelDeg}deg) rotateX(${tiltDeg}deg) scale(${scaleVal})`,
          transformStyle: "preserve-3d",
        }}
      >
        <Img
          src={staticFile("frames/" + frameFilename)}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const DynamicRoot: React.FC = () => {
  return (
    <Composition
      id="Pan3D"
      component={VideoTransition3D}
      durationInFrames={300}
      fps={60}
      width={3840}
      height={2160}
    />
  );
};
