"use client";

interface Props {
  gradientBackgroundStart?: string;
  gradientBackgroundEnd?: string;
  firstColor?: string;
  secondColor?: string;
  thirdColor?: string;
  fourthColor?: string;
  fifthColor?: string;
  blendingValue?: string;
}

export function BackgroundGradientAnimation({
  gradientBackgroundStart = "rgb(0, 0, 20)",
  gradientBackgroundEnd = "rgb(0, 10, 40)",
  firstColor = "0, 57, 152",
  secondColor = "194, 0, 23",
  thirdColor = "0, 57, 152",
  fourthColor = "194, 0, 23",
  fifthColor = "255, 255, 255",
  blendingValue = "screen",
}: Props) {
  const orbBase: React.CSSProperties = {
    position: "absolute",
    borderRadius: "50%",
    width: "80%",
    height: "80%",
    top: "10%",
    left: "10%",
    mixBlendMode: blendingValue as React.CSSProperties["mixBlendMode"],
  };

  return (
    <div
      className="fixed inset-0 -z-10 overflow-hidden pointer-events-none"
      style={{
        background: `linear-gradient(40deg, ${gradientBackgroundStart}, ${gradientBackgroundEnd})`,
      }}
    >
      <div className="absolute inset-0" style={{ filter: "blur(40px)" }}>
        {/* Fox Blue: slow drift */}
        <div
          style={{
            ...orbBase,
            background: `radial-gradient(circle at center, rgba(${firstColor}, 0.7) 0, rgba(${firstColor}, 0) 50%)`,
            animation: "orb-first 20s ease infinite",
            opacity: 0.7,
          }}
        />
        {/* Fox Crimson: medium rotation */}
        <div
          style={{
            ...orbBase,
            background: `radial-gradient(circle at center, rgba(${secondColor}, 0.65) 0, rgba(${secondColor}, 0) 50%)`,
            animation: "orb-second 15s ease infinite",
            opacity: 0.65,
          }}
        />
        {/* Fox Blue: complex path */}
        <div
          style={{
            ...orbBase,
            background: `radial-gradient(circle at center, rgba(${thirdColor}, 0.6) 0, rgba(${thirdColor}, 0) 50%)`,
            animation: "orb-third 25s ease infinite",
            opacity: 0.6,
          }}
        />
        {/* Fox Crimson: simple oscillation */}
        <div
          style={{
            ...orbBase,
            background: `radial-gradient(circle at center, rgba(${fourthColor}, 0.6) 0, rgba(${fourthColor}, 0) 50%)`,
            animation: "orb-fourth 18s ease infinite",
            opacity: 0.6,
          }}
        />
        {/* White: very subtle brightening */}
        <div
          style={{
            ...orbBase,
            background: `radial-gradient(circle at center, rgba(${fifthColor}, 0.4) 0, rgba(${fifthColor}, 0) 50%)`,
            animation: "orb-fifth 22s ease infinite",
            opacity: 0.25,
          }}
        />
      </div>
    </div>
  );
}
