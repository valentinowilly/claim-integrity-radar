import { Moon, Sun } from "lucide-react";
import { toggleTheme, useTheme } from "../theme/theme";

/** Light/dark switch; the choice is remembered on this device. */
export function ThemeToggle({ className = "" }: { className?: string }) {
  const theme = useTheme();
  const dark = theme === "dark";
  const label = dark ? "Gunakan tema terang" : "Gunakan tema gelap";
  return <button type="button" className={`theme-toggle ${className}`.trim()} onClick={toggleTheme}
    aria-label={label} title={label} aria-pressed={dark}>
    {dark ? <Sun size={17} aria-hidden="true" /> : <Moon size={17} aria-hidden="true" />}
  </button>;
}
