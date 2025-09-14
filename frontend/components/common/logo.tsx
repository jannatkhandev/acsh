"use client";
import Image from "next/image";
import { useTheme } from "next-themes";

type LogoProps = {
  className?: string;
  height?: number
  width?: number
};

const Logo = ({ className, height = 40, width = 40}: LogoProps) => {
  const src = "/images/nora.webp"

  return (
    <div className={className} style={{borderRadius: '5px', overflow: 'hidden'}}>
      <Image 
        alt="Nora" 
        src={src} 
        width={width} 
        height={height} 
        style={{ width: width, height: height }}
        className="transition-opacity duration-300"
      />
    </div>
  );
};

export default Logo;
