import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import { CardImageFrame } from "./CardImageFrame";
import styles from "./AtlasPrimitives.module.css";

/** Explicit opt-in: importing this module changes no existing route or token. */
export function AtlasVisualSystem({ children }: { children: ReactNode }) {
  return <div className={styles.system}>{children}</div>;
}

export function AtlasSectionIntro({
  id,
  number,
  title,
  description,
  level = 2,
}: {
  id: string;
  number?: string;
  title: string;
  description?: ReactNode;
  level?: 2 | 3;
}) {
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <div className={styles.intro}>
      {number && <span className={styles.number} aria-hidden="true">{number}</span>}
      <div className={styles.introCopy}>
        <Heading id={id} className={styles.heading}>{title}</Heading>
        {description && <div className={styles.description}>{description}</div>}
      </div>
    </div>
  );
}

/** A drawn separator, never a navigation path or a data series. */
export function AtlasDivider() {
  return (
    <svg className={styles.divider} viewBox="0 0 1000 24" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <path d="M0 12 H340 C370 12 380 5 410 5 S450 19 480 19 S520 5 550 5 S590 12 620 12 H1000" />
    </svg>
  );
}

/** Geometry is behind an opaque content layer wherever the caller needs one.
 * Only the SVG clips; content, artwork corners and focus rings never do. */
export function AtlasMapSurface({ children }: { children: ReactNode }) {
  return (
    <div className={styles.mapSurface}>
      <svg className={styles.mapGeometry} viewBox="0 0 600 500" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
        <path className={styles.chartLines} d="M100 0 V500 M200 0 V500 M300 0 V500 M400 0 V500 M500 0 V500 M0 100 H600 M0 200 H600 M0 300 H600 M0 400 H600" />
        <path className={styles.routeLine} d="M28 450 H70 Q90 450 90 430 V380 M500 48 H530 Q550 48 550 68 V118" />
        <circle className={styles.waypoint} cx="90" cy="380" r="4" />
        <circle className={styles.waypoint} cx="500" cy="48" r="4" />
      </svg>
      <div className={styles.mapContent}>{children}</div>
    </div>
  );
}

type ArtworkProps = Omit<ComponentProps<typeof CardImageFrame>, "size" | "padded" | "accent">;

/** Pass through the selected exact image and its geometry. The existing frame
 * owns bounded placement, intrinsic-size validation and missing-image states. */
export function AtlasArtworkStage({ image, caption }: { image: ArtworkProps; caption?: ReactNode }) {
  return (
    <figure className={styles.stage}>
      <AtlasMapSurface>
        <div className={styles.stageInset}>
          <div className={styles.artwork}>
            <CardImageFrame key={`${image.imageUrl ?? "missing"}:${image.cardCode}`} {...image} size="full" padded />
          </div>
        </div>
      </AtlasMapSurface>
      {caption && <figcaption className={styles.caption}>{caption}</figcaption>}
    </figure>
  );
}

/** The caller supplies the existing release URL and the actual release code.
 * No set-name lookup, code normalization, count or membership inference. */
export function AtlasReleaseDestination({ releaseCode, href }: { releaseCode: string; href: string }) {
  return (
    <Link href={href} prefetch={false} className={styles.destination}>
      <span className={styles.destinationDot} aria-hidden="true" />
      <span className={styles.destinationCopy}>
        <span className={styles.releaseCode}>{releaseCode}</span>{" "}
        <span className={styles.destinationLabel}>Explore release</span>
      </span>
      <span className={styles.destinationArrow} aria-hidden="true">→</span>
    </Link>
  );
}
