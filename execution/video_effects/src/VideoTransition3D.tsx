import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
  Easing,
  staticFile,
  getInputProps,
} from "remotion";

interface VideoTransition3DProps {
  frameDir?: string;
  frameCount: number;
  playbackRate?: number;
  swivelStart?: number;
  swivelEnd?: number;
  tiltStart?: number;
  tiltEnd?: number;
  perspective?: number;
  scale?: number;
  bgColor?: string;
}

export const VideoTransition3D: React.FC<VideoTransition3DProps> = ({
  frameDir = "frames",
  frameCount,
  playbackRate = 1,
  swivelStart = 3.5,
  swivelEnd = -3.5,
  tiltStart = 1.7,
  tiltEnd = 1.7,
  perspective = 1000,
  scale = 0.985,
  bgColor = "#2d3436",
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const sourceFrameIndex = Math.min(
    Math.floor(frame * playbackRate),
    frameCount - 1
  );

  const progress = interpolate(frame, [0, durationInFrames], [0, 1], {
    extrapolateRight: "clamp",
  });

  const swivelDeg = interpolate(progress, [0, 1], [swivelStart, swivelEnd]);
  const tiltDeg = interpolate(progress, [0, 1], [tiltStart, tiltEnd]);

  const frameNum = String(sourceFrameIndex + 1).padStart(4, "0");
  const frameFilename = `frame_${frameNum}.jpg`;

  return (
    <AbsoluteFill
      style={{ perspective: `${perspective}px`, backgroundColor: bgColor }}
    >
      <AbsoluteFill
        style={{
          transform: `rotateY(${swivelDeg}deg) rotateX(${tiltDeg}deg) scale(${scale})`,
          transformStyle: "preserve-3d",
        }}
      >
        <Img
          src={staticFile(`${frameDir}/${frameFilename}`)}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const VideoTransition3DDynamic: React.FC = () => {
  const props = getInputProps() as {
    frameCount: number;
    playbackRate: number;
    swivelStart: number;
    swivelEnd: number;
    tiltStart: number;
    tiltEnd: number;
    perspective: number;
  };

  return (
    <VideoTransition3D
      frameCount={props.frameCount}
      playbackRate={props.playbackRate}
      swivelStart={props.swivelStart}
      swivelEnd={props.swivelEnd}
      tiltStart={props.tiltStart}
      tiltEnd={props.tiltEnd}
      perspective={props.perspective}
    />
  );
};
