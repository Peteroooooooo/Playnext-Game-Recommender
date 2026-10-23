import { useEffect, useRef } from "react";
import { art } from "../present";

/**
 * Blurred game hero art behind the page. A new image fades in on top over --bd-fade while the old one stays
 * fully visible underneath, so a change takes exactly the fade time with no dark dip in the middle.
 */
export function Backdrop({ appid }: { appid: number | null }) {
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = box.current;
    if (!root || appid == null) return undefined;
    let live = true;
    let removeT = 0;
    const img = new Image();
    img.alt = "";
    img.decoding = "async";
    img.addEventListener("load", () => {
      if (!live) return;
      const old = Array.from(root.children);
      const fade = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--bd-fade")) * 1000 || 0;
      root.append(img);
      requestAnimationFrame(() => requestAnimationFrame(() => img.classList.add("on")));
      removeT = window.setTimeout(() => old.forEach((o) => o.remove()), fade + 100);
    });
    img.addEventListener("error", () => {
      if (!img.dataset.fb) {
        img.dataset.fb = "1";
        img.src = art(appid, "header.jpg");
      }
    });
    img.src = art(appid, "library_hero.jpg");
    return () => {
      // a newer image takes over; this one may still be fading in, the next load removes it
      live = false;
      window.clearTimeout(removeT);
    };
  }, [appid]);

  return <div className="backdrop" ref={box} aria-hidden="true" />;
}
