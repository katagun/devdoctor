export const NOTHING_ENABLED_PROVIDER = "__diskdoctor_nothing_enabled__";

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
