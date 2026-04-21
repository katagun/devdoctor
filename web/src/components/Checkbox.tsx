export function Checkbox({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label?: string;
}) {
  return (
    <span
      role="checkbox"
      aria-checked={checked}
      aria-label={label}
      tabIndex={0}
      onClick={() => onChange(!checked)}
      onKeyDown={(e) => {
        if (e.key === " ") {
          e.preventDefault();
          onChange(!checked);
        }
      }}
      className={`relative inline-block w-[13px] h-[13px] rounded-sm border cursor-pointer ${
        checked
          ? "bg-risk-safe border-risk-safe after:content-[''] after:absolute after:inset-[2px] after:border-l-2 after:border-b-2 after:border-[#0b0e13] after:rotate-[-45deg]"
          : "border-border-strong"
      }`}
    />
  );
}
