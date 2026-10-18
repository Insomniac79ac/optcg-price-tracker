import styles from "./StatusPage.module.css";

/** The homepage's repeating current marks; decorative. */
export function StatusWave() {
  return <svg className={styles.wave} viewBox="0 0 1200 24" preserveAspectRatio="none" aria-hidden="true" focusable="false">
    <path d="M0 12 Q30 2 60 12 T120 12 T180 12 T240 12 T300 12 T360 12 T420 12 T480 12 T540 12 T600 12 T660 12 T720 12 T780 12 T840 12 T900 12 T960 12 T1020 12 T1080 12 T1140 12 T1200 12" />
  </svg>;
}
