// One source switch removes every decorative mascot, including its image loads
// and animation timers. A build can also opt out with VITE_LABCAT_MASCOTS=false.
export const ENABLE_LABCAT_MASCOTS = true;
const buildSetting = import.meta.env?.VITE_LABCAT_MASCOTS;
export const LABCAT_MASCOTS_ENABLED =
  ENABLE_LABCAT_MASCOTS &&
  !/^(false|0|off)$/i.test(
    typeof buildSetting === "string" ? buildSetting.trim() : "",
  );

export const LABCAT_COMPLETION_MS = 2_400;
