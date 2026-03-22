import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
  Easing,
  staticFile,
  spring,
} from "remotion";

interface Transition3DProps {
  imageSrc: string;
  swivelStart?: number;
  swivelEnd?: number;
  tiltStart?: number;
  tiltEnd?: number;
  perspective?: number;
  scale?: number;
  bgColor?: string;
  easeType?: "linear" | "easeOut" | "easeInOut" | "spring";
}

export const Transition3D: React.FC<Transition3DProps> = ({
  imageSrc,
  swivelStart = 5,
  swivelEnd = -5,
  tiltStart = 2,
  tiltEnd = 2,
  perspective = 1000,
  scale = 0.985,
  bgColor = "#2d3436",
  easeType = "easeOut",
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();

  let progress: number;
  if (easeType === "spring") {
    progress = spring({
      frame,
      fps,
      config: { damping: 15, stiffness: 80, mass: 0.5 },
    });
  } else if (easeType === "easeInOut") {
    progress = interpolate(frame, [0, durationInFrames], [0, 1], {
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.cubic),
    });
  } else if (easeType === "easeOut") {
    progress = interpolate(frame, [0, durationInFrames], [0, 1], {
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    });
  } else {
    progress = interpolate(frame, [0, durationInFrames], [0, 1], {
      extrapolateRight: "clamp",
    });
  }

  const swivelDeg = interpolate(progress, [0, 1], [swivelStart, swivelEnd]);
  const tiltDeg = interpolate(progress, [0, 1], [tiltStart, tiltEnd]);

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
          src={staticFile(imageSrc)}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

interface Transition3DVideoProps {
  videoSrc: string;
  playbackRate?: number;
  swivelStart?: number;
  swivelEnd?: number;
  tiltStart?: number;
  tiltEnd?: number;
  perspective?: number;
  scale?: number;
  bgColor?: string;
  easeType?: "linear" | "easeOut" | "easeInOut" | "spring";
}

export const Transition3DVideo: React.FC<Transition3DVideoProps> = ({
  videoSrc,
  playbackRate = 7,
  swivelStart = 5,
  swivelEnd = -5,
  tiltStart = 2,
  tiltEnd = 2,
  perspective = 1000,
  scale = 0.985,
  bgColor = "#2d3436",
  easeType = "easeOut",
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();

  let progress: number;
  if (easeType === "spring") {
    progress = spring({
      frame,
      fps,
      config: { damping: 15, stiffness: 80, mass: 0.5 },
    });
  } else if (easeType === "easeInOut") {
    progress = interpolate(frame, [0, durationInFrames], [0, 1], {
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.cubic),
    });
  } else if (easeType === "easeOut") {
    progress = interpolate(frame, [0, durationInFrames], [0, 1], {
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    });
  } else {
    progress = interpolate(frame, [0, durationInFrames], [0, 1], {
      extrapolateRight: "clamp",
    });
  }

  const swivelDeg = interpolate(progress, [0, 1], [swivelStart, swivelEnd]);
  const tiltDeg = interpolate(progress, [0, 1], [tiltStart, tiltEnd]);

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
        <video
          src={staticFile(videoSrc)}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
          muted
          playsInline
        />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
