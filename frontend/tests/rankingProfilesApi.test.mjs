import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { afterEach, mock, test } from "node:test";
import ts from "typescript";
const compiled = ts.transpileModule(
  await readFile(
    new URL("../src/rankingProfilesApi.ts", import.meta.url),
    "utf8",
  ),
  {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ES2022,
    },
  },
).outputText;
const { rankingProfilesApi, relativeWeights, matchingPreset } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);
globalThis.window = { setTimeout, clearTimeout };
afterEach(() => mock.restoreAll());
const profile = {
  id: "profile-1",
  name: "Priorities",
  material_class: "oxide",
  application: "dielectric",
  importance: { band_gap: 0.8, dielectric_total: 0.8 },
  normalized_weights: { band_gap: 0.5, dielectric_total: 0.5 },
  preset: true,
  created_at: "2026-09-09",
  updated_at: "2026-09-09",
};
const attributes = ["band_gap", "dielectric_total"].map((id) => ({
  id,
  label: id,
  category: "Electronic",
  description: "Test catalog description",
  source_field: id,
  supported: true,
  availability_note: "Availability differs by source.",
}));
const result = {
  catalog: {
    attributes,
    material_classes: [
      { id: "oxide", label: "Oxide", scope: "Current retrieval" },
    ],
    applications: [
      { id: "dielectric", label: "Dielectric", scope: "Current application" },
    ],
  },
  profiles: [profile],
  active_profile_id: profile.id,
};
test("independent importance values need not sum to one", () => {
  assert.deepEqual(relativeWeights({ gap: 0.8, stability: 0.8 }), {
    gap: 0.5,
    stability: 0.5,
  });
  assert.deepEqual(relativeWeights({ gap: 0 }), { gap: 0 });
});
test("unsupported selected attributes retain their relative share rather than fabricate evidence", async () => {
  mock.method(globalThis, "fetch", async () =>
    Response.json({
      ...result,
      catalog: {
        ...result.catalog,
        attributes: attributes.map((item) => ({ ...item, supported: false })),
      },
    }),
  );
  const loaded = await rankingProfilesApi.list();
  assert.equal(loaded.catalog.attributes[0].supported, false);
  assert.deepEqual(loaded.profiles[0].importance, profile.importance);
});
test("catalog and profile loading rejects invented attribute IDs", async () => {
  mock.method(globalThis, "fetch", async () =>
    Response.json({
      ...result,
      profiles: [
        {
          ...profile,
          importance: { user_claim: 1 },
          normalized_weights: { user_claim: 1 },
        },
      ],
    }),
  );
  await assert.rejects(rankingProfilesApi.list(), /unsupported response/);
});
test("saving a custom profile preserves independent raw preferences", async () => {
  const fetch = mock.method(globalThis, "fetch", async () =>
    Response.json({ ...profile, preset: false }),
  );
  const input = {
    name: profile.name,
    material_class: profile.material_class,
    application: profile.application,
    importance: profile.importance,
  };
  await rankingProfilesApi.save(input);
  assert.deepEqual(JSON.parse(fetch.mock.calls[0].arguments[1].body), input);
  assert.equal(fetch.mock.calls[0].arguments[1].method, "POST");
  assert.equal(fetch.mock.calls[0].arguments[1].credentials, "same-origin");
});
test("activation targets the selected profile only", async () => {
  const fetch = mock.method(globalThis, "fetch", async () =>
    Response.json({ active_profile_id: profile.id, profile }),
  );
  assert.deepEqual(await rankingProfilesApi.activate(profile.id), profile);
  assert.equal(
    fetch.mock.calls[0].arguments[0],
    "/api/ranking-profiles/profile-1/activate",
  );
  await assert.rejects(
    rankingProfilesApi.activate("other-profile"),
    /unsupported response/,
  );
});
test("an uncertain profile save is not automatically retried", async () => {
  const fetch = mock.method(globalThis, "fetch", async () =>
    Response.json({ detail: "PRIVATE_VALUE" }, { status: 500 }),
  );
  await assert.rejects(
    rankingProfilesApi.save({
      name: "New",
      material_class: "oxide",
      application: "test",
      importance: { band_gap: 0.5 },
    }),
    (error) => {
      assert.match(error.message, /Reload saved ranking profiles/);
      assert.ok(!error.message.includes("PRIVATE_VALUE"));
      return true;
    },
  );
  assert.equal(fetch.mock.calls.length, 1);
});

test("material class and application selection loads matching preset attributes", () => {
  const highK = {
    ...profile,
    id: "high-k",
    application: "high_k",
    importance: { dielectric_total: 1 },
    normalized_weights: { dielectric_total: 1 },
  };
  const ceramic = {
    ...profile,
    id: "ceramic",
    material_class: "ceramic",
    application: "stiffness",
    importance: { stiffness: 0.9 },
    normalized_weights: { stiffness: 1 },
  };
  const custom = { ...highK, id: "custom-high-k", preset: false };
  const profiles = [custom, profile, highK, ceramic];
  assert.equal(matchingPreset(profiles, "oxide")?.id, profile.id);
  assert.deepEqual(matchingPreset(profiles, "oxide", "high_k")?.importance, {
    dielectric_total: 1,
  });
  assert.equal(matchingPreset(profiles, "ceramic")?.id, ceramic.id);
  assert.equal(matchingPreset(profiles, "ceramic", "high_k"), undefined);
});

test("optional minimum gap is preserved independently from weights and malformed values never reach saves", async () => {
  let response = { ...profile, minimum_band_gap_ev: 2 };
  const fetch = mock.method(globalThis, "fetch", async () =>
    Response.json(response),
  );
  const input = {
    name: profile.name,
    material_class: profile.material_class,
    application: profile.application,
    importance: profile.importance,
    minimum_band_gap_ev: 2,
  };
  assert.equal((await rankingProfilesApi.save(input)).minimum_band_gap_ev, 2);
  assert.deepEqual(JSON.parse(fetch.mock.calls[0].arguments[1].body), input);
  assert.deepEqual(
    relativeWeights(input.importance),
    profile.normalized_weights,
  );
  for (const value of [null, 0, 100]) {
    response = { ...profile, minimum_band_gap_ev: value };
    assert.equal(
      (await rankingProfilesApi.save({ ...input, minimum_band_gap_ev: value }))
        .minimum_band_gap_ev,
      value,
    );
  }
  const before = fetch.mock.calls.length;
  for (const value of ["2", true, -0.01, 100.01, NaN, Infinity, {}]) {
    await assert.rejects(
      rankingProfilesApi.save({ ...input, minimum_band_gap_ev: value }),
      /unsupported response/,
    );
  }
  assert.equal(
    fetch.mock.calls.length,
    before,
    "invalid preference never becomes a mutation",
  );
});

test("minimum gap is strictly validated on list and activation while omitted historical settings remain omitted", async () => {
  const fetch = mock.method(globalThis, "fetch", async () =>
    Response.json(result),
  );
  const loaded = await rankingProfilesApi.list();
  assert.equal(Object.hasOwn(loaded.profiles[0], "minimum_band_gap_ev"), false);
  for (const value of ["2", true, -1, 101, {}]) {
    const broken = { ...profile, minimum_band_gap_ev: value };
    fetch.mock.mockImplementation(async () =>
      Response.json({ ...result, profiles: [broken] }),
    );
    await assert.rejects(rankingProfilesApi.list(), /unsupported response/);
    fetch.mock.mockImplementation(async () =>
      Response.json({ active_profile_id: profile.id, profile: broken }),
    );
    await assert.rejects(
      rankingProfilesApi.activate(profile.id),
      /unsupported response/,
    );
  }
});

test("target gap and soft tolerance remain optional preferences with strict validated transport", async () => {
  const input = {
    name: profile.name,
    material_class: profile.material_class,
    application: profile.application,
    importance: profile.importance,
    target_band_gap_ev: 1.78,
    band_gap_tolerance_ev: 0.2,
  };
  const fetch = mock.method(globalThis, "fetch", async () =>
    Response.json({ ...profile, ...input }),
  );
  const saved = await rankingProfilesApi.save(input);
  assert.equal(saved.target_band_gap_ev, 1.78);
  assert.equal(saved.band_gap_tolerance_ev, 0.2);
  assert.deepEqual(JSON.parse(fetch.mock.calls[0].arguments[1].body), input);
  const before = fetch.mock.calls.length;
  for (const patch of [
    { target_band_gap_ev: -1 },
    { target_band_gap_ev: "1.78" },
    { target_band_gap_ev: true },
    { target_band_gap_ev: 101 },
    { target_band_gap_ev: null },
    { band_gap_tolerance_ev: 0 },
    { band_gap_tolerance_ev: 101 },
    { band_gap_tolerance_ev: "0.2" },
    { band_gap_tolerance_ev: Infinity },
  ]) {
    await assert.rejects(
      rankingProfilesApi.save({ ...input, ...patch }),
      /unsupported response/,
    );
  }
  assert.equal(
    fetch.mock.calls.length,
    before,
    "invalid target/tolerance cannot produce writes",
  );
  for (const patch of [
    { target_band_gap_ev: -1 },
    { band_gap_tolerance_ev: 0 },
    { target_band_gap_ev: null, band_gap_tolerance_ev: 0.2 },
  ]) {
    fetch.mock.mockImplementation(async () =>
      Response.json({
        ...result,
        profiles: [{ ...profile, ...input, ...patch }],
      }),
    );
    await assert.rejects(rankingProfilesApi.list(), /unsupported response/);
  }
  fetch.mock.mockImplementation(async () =>
    Response.json({ ...profile, target_band_gap_ev: 1.78 }),
  );
  assert.equal(
    Object.hasOwn(
      await rankingProfilesApi.save({
        ...input,
        band_gap_tolerance_ev: undefined,
      }),
      "band_gap_tolerance_ev",
    ),
    false,
  );
});
