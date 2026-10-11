import React from "react";
import "./DotPattern.css";

/**
 * DotPattern - React Bits component for a high-tech dotted background
 */
const DotPattern = ({ width = 16, height = 16, cx = 1, cy = 1, cr = 1, className = "" }) => {
  return (
    <div className={`dot-pattern-wrapper ${className}`}>
      <svg width="100%" height="100%" className="dot-pattern-svg">
        <defs>
          <pattern
            id="dot-pattern"
            width={width}
            height={height}
            patternUnits="userSpaceOnUse"
            patternContentUnits="userSpaceOnUse"
          >
            <circle cx={cx} cy={cy} r={cr} fill="currentColor" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#dot-pattern)" />
      </svg>
    </div>
  );
};

export default DotPattern;
