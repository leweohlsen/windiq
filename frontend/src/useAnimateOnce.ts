/** True for the first ~1.6 s after mount so charts run their intro animation
 * once; afterwards data updates render in place instead of re-animating.
 * Users with prefers-reduced-motion never animate. */
import { useEffect, useState } from "react";

/** Covers recharts' default animation duration (1.5 s). */
const INTRO_MS = 1_600;

export function useAnimateOnce(): boolean {
  const [animate, setAnimate] = useState(
    () => !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    if (!animate) return;
    const timer = setTimeout(() => setAnimate(false), INTRO_MS);
    return () => clearTimeout(timer);
  }, [animate]);

  return animate;
}
