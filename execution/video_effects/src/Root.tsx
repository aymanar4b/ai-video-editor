import React from "react";
import { Composition } from "remotion";
import { Transition3D } from "./Transition3D";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Transition3DDemo"
        component={Transition3D}
        durationInFrames={30}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{
          imageSrc: "frames/frame_0001.jpg",
          swivelStart: 3.5,
          swivelEnd: -3.5,
          tiltStart: 1.7,
          tiltEnd: 1.7,
          easeType: "easeOut" as const,
        }}
      />
      <Composition
        id="Transition3DSpring"
        component={Transition3D}
        durationInFrames={45}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{
          imageSrc: "frames/frame_0001.jpg",
          swivelStart: 5,
          swivelEnd: -5,
          tiltStart: 3,
          tiltEnd: 1,
          easeType: "spring" as const,
        }}
      />
      <Composition
        id="Transition3DSubtle"
        component={Transition3D}
        durationInFrames={20}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{
          imageSrc: "frames/frame_0001.jpg",
          swivelStart: 2,
          swivelEnd: -2,
          tiltStart: 1,
          tiltEnd: 1,
          easeType: "linear" as const,
        }}
      />
    </>
  );
};
