describe("interface language", () => {
  beforeEach(() => {
    localStorage.removeItem("robotpilotLangV2");
    vi.resetModules();
  });

  test("new browsers start in simplified Chinese and can switch to English", async () => {
    const { getLang, setLang, translate } = await import("./i18n");
    expect(getLang()).toBe("zh-CN");
    expect(translate("Map")).toBe("地图");
    setLang("en");
    expect(translate("Map")).toBe("Map");
    expect(localStorage.getItem("robotpilotLangV2")).toBe("en");
  });

  test("an unsupported language cannot replace the active locale", async () => {
    const { getLang, setLang } = await import("./i18n");
    setLang("unsupported");
    expect(getLang()).toBe("zh-CN");
  });
});
