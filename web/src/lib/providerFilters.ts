export const NOTHING_ENABLED_PROVIDER = "__devdoctor_nothing_enabled__";

export function diskProviderParam(
  providers: Array<{ name: string }> | undefined,
  disabled: Set<string>,
): string | undefined {
  if (!providers || disabled.size === 0) return undefined;
  const enabled = providers
    .filter((provider) => !disabled.has(provider.name))
    .map((provider) => provider.name);
  return enabled.length ? enabled.join(",") : NOTHING_ENABLED_PROVIDER;
}

export function memoryProviderIds(
  providers: Array<{ id: string }> | undefined,
  disabled: Set<string>,
): string[] | undefined {
  if (!providers) return undefined;
  return providers
    .filter((provider) => !disabled.has(provider.id))
    .map((provider) => provider.id);
}

/**
 * Whether the disk scan's provider filter is final. It only depends on the
 * provider list when some are disabled; until that list loads, a scan would go
 * out unfiltered and then again filtered. When the provider list failed to
 * load, fall back to an unfiltered scan rather than waiting forever: a real
 * fault then surfaces as the scan's own error instead of a stuck "scanning…".
 */
export function diskScanReady(
  providers: Array<{ name: string }> | undefined,
  disabled: Set<string>,
  providersFailed: boolean = false,
): boolean {
  return disabled.size === 0 || providers !== undefined || providersFailed;
}
