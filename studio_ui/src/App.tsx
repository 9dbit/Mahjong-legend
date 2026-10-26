import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  api,
  ApiError,
  assetURL,
  errorText,
  formatDate,
  setSession,
  shorten,
} from "./api";
import type {
  Asset,
  Draft,
  Job,
  Release,
  Session,
  StudioConfig,
  Validation,
} from "./types";
import {
  Badge,
  Empty,
  Field,
  Icon,
  Metric,
  Notice,
  NumberField,
  Section,
} from "./components";
import {
  BettingEditor,
  RulesEditor,
  SceneEditor,
  TileEditor,
} from "./ConfigEditors";
import AudioStudio from "./AudioStudio";
const navigation = [
  { id: "overview", title: "Overview", caption: "Release workspace" },
  { id: "betting", title: "Betting & Auto", caption: "Credit policy" },
  { id: "rules", title: "Rules & Paytable", caption: "Game mathematics" },
  { id: "tiles", title: "Tile Studio", caption: "Artwork & variants" },
  { id: "scene", title: "Scene & Controls", caption: "Canvas composition" },
  { id: "audio", title: "Audio Studio", caption: "Clips, events & mixer" },
  { id: "math", title: "Math Lab", caption: "Simulation & evidence" },
  { id: "preview", title: "Preview & QA", caption: "Play your draft" },
  { id: "releases", title: "Releases & History", caption: "Publish & restore" },
  { id: "settings", title: "Access & Settings", caption: "Workspace details" },
] as const;
type Page = (typeof navigation)[number]["id"];
type Overview = {
  active_release?: Release | null;
  stats?: Record<string, number>;
  environment?: string;
  runtime_version?: string;
  engine_hash?: string;
};
const clone = <T,>(v: T): T => structuredClone(v);
function loadSetupToken() {
  const params = new URLSearchParams(location.hash.slice(1));
  const token = params.get("setup") || "";
  if (token) {
    history.replaceState(null, "", location.pathname + location.search);
  }
  return token;
}
const initialSetupToken = loadSetupToken();
export default function App() {
  const [session, updateSession] = useState<Session | null>(null),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [page, setPage] = useState<Page>("overview"),
    [navOpen, setNavOpen] = useState(false),
    [overview, setOverview] = useState<Overview>({}),
    [drafts, setDrafts] = useState<Draft[]>([]),
    [draft, setDraft] = useState<Draft | null>(null),
    [config, setConfig] = useState<StudioConfig | null>(null),
    [assets, setAssets] = useState<Asset[]>([]),
    [jobs, setJobs] = useState<Job[]>([]),
    [releases, setReleases] = useState<Release[]>([]);
  const [draftName, setDraftName] = useState(""),
    [preview, setPreview] = useState(""),
    [previewWidth, setPreviewWidth] = useState("390"),
    [previewHeight, setPreviewHeight] = useState("844");
  const [dialog, setDialog] = useState<{
      kind: "publish" | "rollback";
      release?: Release;
    } | null>(null),
    [reason, setReason] = useState(""),
    [conflict, setConflict] = useState(false),
    [setupToken] = useState(initialSetupToken);
  const dirty = !!(
    draft &&
    config &&
    JSON.stringify(draft.config) !== JSON.stringify(config)
  );
  const permissions = session?.user?.permissions || [];
  const canEdit = permissions.includes("edit"),
    canPublish = permissions.includes("publish"),
    canTest = permissions.includes("test");
  const active = overview.active_release || releases.find((r) => r.active);
  const currentNav = navigation.find((n) => n.id === page)!;
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }, [page]);
  const requestSession = useCallback(async () => {
    const s = await api<Session>("session");
    setSession(s);
    updateSession(s);
    return s;
  }, []);
  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([
      api<Overview>("overview"),
      api<{ drafts: Draft[] }>("drafts"),
      api<{ assets: Asset[] }>("assets"),
      api<{ jobs: Job[] }>("jobs"),
      api<{ releases: Release[] }>("releases"),
    ]);
    const [o, d, a, j, r] = results;
    if (o.status === "fulfilled") setOverview(o.value);
    if (d.status === "fulfilled") setDrafts(d.value.drafts);
    if (a.status === "fulfilled") setAssets(a.value.assets);
    if (j.status === "fulfilled") setJobs(j.value.jobs);
    if (r.status === "fulfilled") setReleases(r.value.releases);
    const failed = results.find((x) => x.status === "rejected");
    if (failed?.status === "rejected") throw failed.reason;
    return d.status === "fulfilled" ? d.value.drafts : [];
  }, []);
  const useDraft = useCallback((d: Draft) => {
    setDraft(d);
    setConfig(clone(d.config));
    setPreview("");
    setConflict(false);
  }, []);
  useEffect(() => {
    let cancelled = false;
    void requestSession()
      .then(async (s) => {
        if (s.authenticated) {
          const list = await refresh();
          if (!cancelled && list.length) {
            const d = await api<Draft>("drafts/" + list[0].id);
            if (!cancelled) useDraft(d);
          }
        }
      })
      .catch((e) => {
        if (!cancelled) setError(errorText(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [requestSession, refresh, useDraft]);
  useEffect(() => {
    if (!session?.authenticated) return;
    const t = setInterval(() => {
      if (document.hidden) return;
      void Promise.allSettled([
        api<{ jobs: Job[] }>("jobs"),
        api<{ assets: Asset[] }>("assets"),
      ]).then(([j, a]) => {
        if (j.status === "fulfilled") setJobs(j.value.jobs);
        if (a.status === "fulfilled") setAssets(a.value.assets);
      });
    }, 6000);
    return () => clearInterval(t);
  }, [session?.authenticated]);
  useEffect(() => {
    if (!dirty) return;
    const listener = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", listener);
    return () => window.removeEventListener("beforeunload", listener);
  }, [dirty]);
  async function run<T>(
    label: string,
    work: () => Promise<T>,
  ): Promise<T | undefined> {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      return await work();
    } catch (e) {
      setError(errorText(e));
      if (e instanceof ApiError) {
        if (e.status === 409 || e.status === 412) setConflict(true);
        if (e.status === 401) void requestSession();
      }
      return undefined;
    } finally {
      setBusy("");
    }
  }
  function update(recipe: (c: StudioConfig) => void) {
    if (!canEdit) return;
    setConfig((prev) => {
      if (!prev) return prev;
      const next = clone(prev);
      recipe(next);
      return next;
    });
  }
  async function save(): Promise<Draft> {
    if (!draft || !config) throw Error("Pilih draft.");
    if (!dirty) return draft;
    const d = await api<Draft>(
      "drafts/" + draft.id,
      "PATCH",
      { name: draft.name, revision: draft.revision, config },
      draft.revision,
    );
    setDraft(d);
    setConfig(clone(d.config));
    setDrafts((prev) => prev.map((v) => (v.id === d.id ? d : v)));
    setConflict(false);
    return d;
  }
  async function selectDraft(id: string) {
    if (dirty) {
      setError("Simpan atau buang perubahan lokal sebelum berpindah draft.");
      return;
    }
    await run("Loading draft", async () =>
      useDraft(await api<Draft>("drafts/" + id)),
    );
  }
  async function createDraft(e: FormEvent) {
    e.preventDefault();
    if (dirty) {
      setError("Simpan atau buang perubahan lokal sebelum membuat draft.");
      return;
    }
    await run("Creating draft", async () => {
      const d = await api<Draft>("drafts", "POST", {
        name: draftName.trim() || "Untitled draft",
      });
      setDrafts((prev) => [d, ...prev]);
      useDraft(d);
      setDraftName("");
      setNotice("Draft dibuat dari rilis aktif.");
    });
  }
  async function validate() {
    await run("Validating", async () => {
      const d = await save();
      const validation = await api<Validation>(
        "drafts/" + d.id + "/validate",
        "POST",
        { revision: d.revision },
        d.revision,
      );
      setDraft((prev) => (prev ? { ...prev, validation } : prev));
      setNotice(
        validation.valid
          ? "Validasi lulus. Review preview sebelum publish."
          : "Validasi menemukan perubahan yang perlu diperbaiki.",
      );
    });
  }
  async function previewDraft() {
    await run("Preparing preview", async () => {
      const d = await save();
      const result = await api<{ url: string }>(
        "drafts/" + d.id + "/preview",
        "POST",
        { revision: d.revision },
        d.revision,
      );
      setPreview(result.url);
      setPage("preview");
    });
  }
  async function upload(file: File, kind: string) {
    await run("Uploading asset", async () => {
      const data = new FormData();
      data.append("file", file);
      data.append("kind", kind);
      const accepted = await api<{ asset: Asset; job: Job }>("assets", "POST", data);
      setAssets((prev) => [accepted.asset, ...prev.filter((item) => item.id !== accepted.asset.id)]);
      setJobs((prev) => [accepted.job, ...prev.filter((item) => item.id !== accepted.job.id)]);
      await refresh();
      setNotice(`Upload diterima. ${file.name} sedang diproses; status dan error worker tersedia di Audio Studio.`);
    });
  }
  async function renderAsset(asset: Asset, recipe: Record<string, unknown>) {
    await run("Rendering asset", async () => {
      const result = await api<{ job: Job }>(
        "assets/" + asset.id + "/render",
        "POST",
        { recipe },
      );
      setJobs((prev) => [
        result.job,
        ...prev.filter((j) => j.id !== result.job.id),
      ]);
      setNotice(
        "Render masuk antrean. Derivative akan muncul di library setelah worker selesai.",
      );
    });
  }
  async function publishOrRollback(e: FormEvent) {
    e.preventDefault();
    if (!dialog) return;
    await run(
      dialog.kind === "publish" ? "Publishing" : "Activating release",
      async () => {
        if (dialog.kind === "publish") {
          if (!draft) throw Error("Pilih draft.");
          await api(
            "drafts/" + draft.id + "/publish",
            "POST",
            { revision: draft.revision, reason },
            draft.revision,
          );
        } else if (dialog.release) {
          await api("releases/" + dialog.release.id + "/activate", "POST", {
            reason,
          });
        }
        setDialog(null);
        setReason("");
        await refresh();
        if (draft) useDraft(await api<Draft>("drafts/" + draft.id));
        setNotice(
          "Rilis aktif diperbarui. Ticket yang sudah terbit tetap memakai snapshot sebelumnya.",
        );
      },
    );
  }
  const workingJobs = jobs.filter((j) =>
    ["queued", "running", "processing", "pending"].includes(j.status),
  );
  const editorProps = config ? { config, update, canEdit } : null;
  const validation =
    typeof draft?.validation?.valid === "boolean"
      ? draft.validation
      : undefined;
  if (loading)
    return (
      <div className="loading-screen">
        <div className="brand-mark">發</div>
        <h1>Game Studio</h1>
        <p>Membuka workspace…</p>
      </div>
    );
  if (!session?.authenticated)
    return (
      <Login
        session={session}
        setupToken={setupToken}
        error={error}
        busy={busy}
        onLogin={async (data, setup) => {
          await run(setup ? "Creating owner" : "Signing in", async () => {
            await api(setup ? "setup" : "login", "POST", data);
            const s = await requestSession();
            if (s.authenticated) {
              const list = await refresh();
              if (list.length)
                useDraft(await api<Draft>("drafts/" + list[0].id));
            }
          });
        }}
        onRetry={() => void run("Connecting", requestSession)}
      />
    );
  return (
    <div className={"studio " + (navOpen ? "nav-open" : "")}>
      <aside className="sidebar">
        <a className="brand" href="/studio/">
          <span className="brand-mark">發</span>
          <span>
            MAHJONG LEGEND<small>GAME STUDIO</small>
          </span>
        </a>
        <div className="workspace-label">
          <span className="status-dot" />{" "}
          {session.environment || overview.environment || "Workspace"}{" "}
          <Badge>v0.9</Badge>
        </div>
        <nav aria-label="Studio sections">
          {navigation.map((item, index) => (
            <button
              key={item.id}
              className={
                (page === item.id ? "active " : "") +
                (index === 7 ? "nav-divider" : "")
              }
              onClick={() => {
                setPage(item.id);
                setNavOpen(false);
              }}
            >
              <Icon name={item.id} />
              <span>{item.title}</span>
              {item.id === "math" && workingJobs.length > 0 && (
                <i>{workingJobs.length}</i>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="user-avatar">
            {session.user?.username?.[0]?.toUpperCase() || "A"}
          </div>
          <div>
            <strong>{session.user?.username}</strong>
            <small>
              {canPublish ? "Owner" : canEdit ? "Editor" : "Tester"}
            </small>
          </div>
          <button
            className="icon-button"
            aria-label="Sign out"
            onClick={() =>
              void run("Signing out", async () => {
                if (dirty)
                  throw Error("Simpan atau buang perubahan sebelum keluar.");
                await api("logout", "POST", {});
                await requestSession();
              })
            }
          >
            <Icon name="logout" size={18} />
          </button>
        </div>
      </aside>
      <button
        className="nav-backdrop"
        aria-label="Tutup navigasi"
        onClick={() => setNavOpen(false)}
      />
      <div className="main">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              aria-label="Buka navigasi"
              onClick={() => setNavOpen(!navOpen)}
            >
              <Icon name="menu" />
            </button>
            <span>Workspace</span>
            <Icon name="chevron" size={14} />
            <strong>{currentNav.title}</strong>
          </div>
          <div className="topbar-right">
            <span className="credits-badge">
              <span className="status-dot" /> Virtual credits
            </span>
            <a
              className="button subtle small"
              href="/"
              target="_blank"
              rel="noopener noreferrer"
            >
              Open game <Icon name="link" size={15} />
            </a>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <p className="eyebrow">{currentNav.caption.toUpperCase()}</p>
              <h1>{currentNav.title}</h1>
              <p>
                {page === "overview"
                  ? "Build, listen, test, and publish with one versioned workspace."
                  : page === "audio"
                    ? "Dari waveform hingga game event, setiap suara punya tempat."
                    : page === "tiles"
                      ? "Satu identitas, dua state, artwork yang sepenuhnya milik Anda."
                      : page === "math"
                        ? "Measure the complete paid round. Keep the evidence with the version."
                        : "Edit draft, validasi hasil, lalu terbitkan perubahan secara atomik."}
              </p>
            </div>
            <div className="heading-actions">
              <button
                className="button subtle"
                disabled={!!busy}
                onClick={() =>
                  void run("Refreshing", async () => {
                    await refresh();
                    setNotice(
                      "Workspace diperbarui. Perubahan lokal tetap tersimpan di editor.",
                    );
                  })
                }
              >
                <Icon name="refresh" size={16} />
                Refresh
              </button>
              {canEdit && draft && (
                <button
                  className="button primary"
                  disabled={!dirty || !!busy}
                  onClick={() =>
                    void run("Saving draft", async () => {
                      await save();
                      setNotice("Draft tersimpan.");
                    })
                  }
                >
                  {busy === "Saving draft" ? "Saving…" : "Save draft"}
                  {dirty && <span className="unsaved-dot" />}
                </button>
              )}
            </div>
          </div>
          {error && (
            <div className="notice danger alert" role="alert">
              <span>{error}</span>
              <button
                className="icon-button"
                aria-label="Dismiss error"
                onClick={() => setError("")}
              >
                <Icon name="close" size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="notice jade alert" role="status">
              <span>{notice}</span>
              <button
                className="icon-button"
                aria-label="Dismiss notice"
                onClick={() => setNotice("")}
              >
                <Icon name="close" size={16} />
              </button>
            </div>
          )}
          {busy && (
            <div className="busy-line" role="status">
              <span />
              {busy}…
            </div>
          )}
          <div className="draft-bar">
            <div className="draft-selector">
              <span className="draft-label">WORKING DRAFT</span>
              <select
                aria-label="Pilih draft"
                value={draft?.id || ""}
                onChange={(e) => void selectDraft(e.target.value)}
              >
                <option value="" disabled>
                  {drafts.length ? "Pilih draft" : "Belum ada draft"}
                </option>
                {drafts.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
              {draft && (
                <Badge tone={dirty ? "gold" : validation?.valid ? "jade" : ""}>
                  {dirty
                    ? "Unsaved"
                    : validation?.valid
                      ? "Validated"
                      : "Draft"}{" "}
                  · r{draft.revision}
                </Badge>
              )}
            </div>
            {draft && (
              <div className="draft-actions">
                {dirty && (
                  <button
                    className="text-button"
                    onClick={() => {
                      setConfig(clone(draft.config));
                      setNotice("Perubahan lokal dibuang.");
                    }}
                  >
                    Discard local
                  </button>
                )}
                {conflict && (
                  <button
                    className="text-button danger-text"
                    onClick={() =>
                      void run("Reloading server draft", async () =>
                        useDraft(await api<Draft>("drafts/" + draft.id)),
                      )
                    }
                  >
                    Muat versi server
                  </button>
                )}
                <button
                  className="button small"
                  disabled={!canTest || !!busy}
                  onClick={() => void previewDraft()}
                >
                  <Icon name="preview" size={15} />
                  Preview
                </button>
                <button
                  className="button small"
                  disabled={!canTest || !!busy}
                  onClick={() => void validate()}
                >
                  <Icon name="check" size={15} />
                  Validate
                </button>
                <button
                  className="button gold small"
                  disabled={
                    !canPublish || dirty || !validation?.valid || !!busy
                  }
                  onClick={() => {
                    setDialog({ kind: "publish" });
                    setReason("");
                  }}
                >
                  Publish
                  <Icon name="chevron" size={14} />
                </button>
              </div>
            )}
          </div>
          {validation && !validation.valid && !dirty && page !== "overview" && (
            <Section title="Validation results">
              <ValidationView validation={validation} />
            </Section>
          )}
          {page === "overview" && (
            <>
              <section className="overview-hero">
                <div>
                  <p className="eyebrow">YOUR GAME, EVERY DETAIL</p>
                  <h2>
                    A considered place
                    <br />
                    to craft your game.
                  </h2>
                  <p>
                    Rules, artwork, and sound. Connected in one release.
                    <br />
                    Ticket yang aktif menjaga ronde tetap konsisten.
                  </p>
                  <div className="inline">
                    <Badge tone="jade">Active release</Badge>
                    <code>
                      {shorten(active?.hash || active?.sha256 || active?.id)}
                    </code>
                  </div>
                </div>
                <div className="hero-tiles">
                  {config &&
                    ["M", "N", "O"].map((id, index) => (
                      <img
                        className={"hero-tile hero-tile-" + index}
                        key={id}
                        src={assetURL(config.tiles[id]?.normal, assets)}
                        alt=""
                      />
                    ))}
                </div>
              </section>
              <div className="metrics-grid">
                <Metric
                  label="Working drafts"
                  value={overview.stats?.drafts ?? drafts.length}
                  detail="Versioned & isolated"
                />
                <Metric
                  label="Assets ready"
                  value={overview.stats?.assets ?? assets.filter((a) => a.is_derivative && a.status === "ready").length}
                  detail={`${assets.length} total assets`}
                />
                <Metric
                  label="Background jobs"
                  value={workingJobs.length}
                  detail="Durable worker queue"
                />
                <Metric
                  label="Draft math"
                  value={
                    config?.math.version || "—"
                  }
                  detail="Working snapshot"
                />
              </div>
              <div className="two-column">
                <Section
                  eyebrow="START A NEW ITERATION"
                  title="Draft workspace"
                  description="Buat draft dari rilis aktif. Upload dan save tidak mengubah game produksi."
                >
                  <form
                    className="create-draft"
                    onSubmit={(e) => void createDraft(e)}
                  >
                    <Field label="Nama draft">
                      <input
                        value={draftName}
                        onChange={(e) => setDraftName(e.target.value)}
                        placeholder="Contoh: Jade sound & tile refinement"
                        maxLength={120}
                        disabled={!canEdit}
                      />
                    </Field>
                    <button
                      className="button primary"
                      disabled={!canEdit || !!busy}
                    >
                      <Icon name="plus" size={17} />
                      Create draft
                    </button>
                  </form>
                  {drafts.slice(0, 4).map((d) => (
                    <button
                      className="draft-list-row"
                      key={d.id}
                      onClick={() => void selectDraft(d.id)}
                    >
                      <div>
                        <strong>{d.name}</strong>
                        <small>
                          Revision {d.revision} ·{" "}
                          {formatDate(d.updated_at || d.created_at)}
                        </small>
                      </div>
                      <Badge tone={draft?.id === d.id ? "jade" : ""}>
                        {draft?.id === d.id ? "Editing" : d.status || "Draft"}
                      </Badge>
                    </button>
                  ))}
                </Section>
                <Section
                  eyebrow="VERSION GATES"
                  title="Validation & readiness"
                  description="Hasil validasi terikat ke hash draft. Edit berikutnya membutuhkan validasi baru."
                >
                  {validation && !dirty ? (
                    <ValidationView validation={validation} />
                  ) : (
                    <Empty
                      icon="shield"
                      title={
                        dirty
                          ? "Perubahan belum divalidasi"
                          : "Belum ada validation receipt"
                      }
                    >
                      Simpan lalu Validate untuk memeriksa config, asset, dan
                      compatibility.
                    </Empty>
                  )}
                  {draft && (
                    <button
                      className="button full"
                      disabled={!canTest || !!busy}
                      onClick={() => void validate()}
                    >
                      Validate this draft
                      <Icon name="check" size={16} />
                    </button>
                  )}
                </Section>
              </div>
              <JobsTable
                jobs={jobs.slice(0, 5)}
                canTest={canTest}
                onCancel={(id) =>
                  void run("Cancelling job", async () => {
                    await api("jobs/" + id + "/cancel", "POST", {});
                    await refresh();
                  })
                }
              />
            </>
          )}
          {["betting", "rules", "tiles", "scene", "audio"].includes(page) &&
            !editorProps && (
              <Empty title="Buat atau pilih draft" icon="rules">
                Konfigurasi editor dimuat dari draft server.
              </Empty>
            )}
          {page === "betting" && editorProps && (
            <BettingEditor {...editorProps} />
          )}
          {page === "rules" && editorProps && <RulesEditor {...editorProps} />}
          {page === "tiles" && editorProps && (
            <TileEditor
              {...editorProps}
              assets={assets}
              onUpload={upload}
              onRender={renderAsset}
            />
          )}
          {page === "scene" && editorProps && (
            <SceneEditor {...editorProps} assets={assets} onUpload={upload} />
          )}
          {page === "audio" && editorProps && (
            <AudioStudio
              jobs={jobs}
              {...editorProps}
              assets={assets}
              onUpload={upload}
              onRender={renderAsset}
              isBusy={!!busy}
              onApplyMusic={async (mode) => {
                await run("Applying background music", async () => {
                  // Commit the complete working draft, not just a nested audio
                  // field. That preserves unsaved edits and checks revision.
                  const saved = await save();
                  const result = await api<Validation>(
                    "drafts/" + saved.id + "/validate",
                    "POST",
                    { revision: saved.revision },
                    saved.revision,
                  );
                  setDraft((prev) =>
                    prev && prev.id === saved.id
                      ? { ...prev, validation: result }
                      : prev,
                  );
                  setNotice(
                    result.valid
                      ? "Background music " + mode + " diterapkan ke draft dan validasi lulus. Klik Publish untuk mengaktifkan di game live."
                      : "Pengaturan musik tersimpan di draft, tetapi validasi belum lulus. Buka Validation results untuk memperbaiki error sebelum Publish.",
                  );
                });
              }}
              onImport={async (path) => {
                await run("Importing baseline audio", async () => {
                  await api("assets/import-baseline", "POST", { path });
                  await refresh();
                  setNotice(
                    "Baseline diimpor. Tunggu derivative siap, lalu pilih hasilnya untuk editing.",
                  );
                });
              }}
              onError={setError}
            />
          )}
          {page === "math" && (
            <MathLab
              draft={draft}
              jobs={jobs}
              canTest={canTest}
              busy={!!busy}
              onSimulate={async (data) => {
                await run("Queuing simulation", async () => {
                  const d = await save();
                  const result = await api<{ job: Job }>(
                    "drafts/" + d.id + "/simulate",
                    "POST",
                    { ...data, revision: d.revision },
                    d.revision,
                  );
                  setJobs((prev) => [result.job, ...prev]);
                  setNotice(
                    "Simulasi masuk antrean. Hasil terikat ke snapshot draft ini.",
                  );
                });
              }}
              onCancel={(id) =>
                void run("Cancelling job", async () => {
                  await api("jobs/" + id + "/cancel", "POST", {});
                  await refresh();
                })
              }
            />
          )}
          {page === "preview" && (
            <Section
              eyebrow="ISOLATED TEST SESSION"
              title="Preview the real game"
              description="Preview memakai renderer game dan snapshot draft. Saldo terpisah dari session pemain."
              actions={
                <button
                  className="button primary"
                  disabled={!draft || !canTest || !!busy}
                  onClick={() => void previewDraft()}
                >
                  <Icon name="play" size={16} />
                  Start draft preview
                </button>
              }
            >
              <div className="preview-toolbar">
                <Field label="Viewport">
                  <select
                    value={previewWidth + "x" + previewHeight}
                    onChange={(e) => {
                      const [w, h] = e.target.value.split("x");
                      setPreviewWidth(w);
                      setPreviewHeight(h);
                    }}
                  >
                    <option value="320x667">Compact · 320 × 667</option>
                    <option value="360x740">Android · 360 × 740</option>
                    <option value="390x844">Portrait · 390 × 844</option>
                    <option value="430x932">Large phone · 430 × 932</option>
                    <option value="844x390">Landscape · 844 × 390</option>
                  </select>
                </Field>
                <Badge tone="gold">TEST · DRAFT</Badge>
                {preview && (
                  <a
                    className="button small"
                    href={preview}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open preview
                    <Icon name="link" size={15} />
                  </a>
                )}
              </div>
              {preview ? (
                <div className="device-stage">
                  <div
                    className="device-frame"
                    style={{
                      width: Number(previewWidth),
                      height: Number(previewHeight),
                    }}
                  >
                    <iframe
                      title="Draft game preview"
                      src={preview}
                      allow="autoplay"
                    />
                  </div>
                </div>
              ) : (
                <Empty icon="preview" title="Preview belum dimulai">
                  Buat session dari draft untuk mencoba Spin, audio, asset, dan
                  menu.
                </Empty>
              )}
              <Notice>
                Ukuran frame membantu verifikasi komposisi. Notch, home
                indicator, audio loudness, dan perilaku installed PWA tetap
                perlu diperiksa di perangkat fisik.
              </Notice>
            </Section>
          )}
          {page === "releases" && (
            <Section
              eyebrow="IMMUTABLE RELEASES"
              title="Release history"
              description="Aktivasi berlaku pada ticket baru. Ronde, ledger, dan replay historis tetap terikat ke versi asal."
            >
              {releases.length ? (
                <div className="release-list">
                  {releases.map((r) => (
                    <div className="release-row" key={r.id}>
                      <div
                        className={
                          "release-dot " + (r.id === active?.id ? "active" : "")
                        }
                      />
                      <div className="release-info">
                        <div>
                          <h3>
                            {r.name ||
                              r.version ||
                              "Release " + shorten(r.id, 8)}
                          </h3>
                          {(r.active || r.id === active?.id) && (
                            <Badge tone="jade">Active</Badge>
                          )}
                        </div>
                        <p>{r.reason || "Immutable release bundle"}</p>
                        <small>
                          {formatDate(r.created_at)} ·{" "}
                          <code>{shorten(r.hash || r.sha256 || r.id, 20)}</code>
                        </small>
                      </div>
                      <button
                        className="button small"
                        disabled={!canPublish || r.id === active?.id || !!busy}
                        onClick={() => {
                          setDialog({ kind: "rollback", release: r });
                          setReason("");
                        }}
                      >
                        Activate
                        <Icon name="refresh" size={15} />
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <Empty icon="releases" title="Belum ada release">
                  Release aktif akan muncul setelah baseline diinisialisasi.
                </Empty>
              )}
            </Section>
          )}
          {page === "settings" && (
            <div className="two-column">
              <Section
                title="Your access"
                description="Permission diverifikasi ulang oleh server pada setiap tindakan."
              >
                <div className="profile-card">
                  <div className="user-avatar large">
                    {session.user?.username?.[0]?.toUpperCase()}
                  </div>
                  <div>
                    <h3>{session.user?.username}</h3>
                    <p>
                      {canPublish ? "Owner" : canEdit ? "Editor" : "Tester"}
                    </p>
                  </div>
                </div>
                <div className="permission-list">
                  {["edit", "test", "publish"].map((p) => (
                    <div key={p}>
                      <span>
                        {p === "edit"
                          ? "Edit draft & upload assets"
                          : p === "test"
                            ? "Preview, validate & Math Lab"
                            : "Publish & activate release"}
                      </span>
                      <Badge tone={permissions.includes(p) ? "jade" : ""}>
                        {permissions.includes(p) ? "Allowed" : "Unavailable"}
                      </Badge>
                    </div>
                  ))}
                </div>
                <p className="footnote">
                  Pengelolaan administrator dilakukan lewat management command
                  server. Tidak ada kredensial default atau key storage di
                  browser.
                </p>
              </Section>
              <Section
                title="Runtime & storage"
                description="File original dan derivative disimpan sebagai object immutable."
              >
                <div className="asset-details">
                  <span>Environment</span>
                  <strong>
                    {session.environment || overview.environment || "Workspace"}
                  </strong>
                  <span>Studio</span>
                  <strong>0.9.1</strong>
                  <span>Schema</span>
                  <strong>{config?.schema_version ?? "—"}</strong>
                  <span>Engine</span>
                  <strong>{shorten(active?.engine_sha256 || overview.engine_hash)}</strong>
                  <span>Image upload</span>
                  <strong>16 MiB · 24 MP</strong>
                  <span>Audio upload</span>
                  <strong>32 MiB · 120s · 2ch</strong>
                </div>
                <Notice>
                  Object original/draft memerlukan akses Studio. Upload tidak
                  pernah mengubah release aktif.
                </Notice>
              </Section>
            </div>
          )}
          <footer className="studio-footer">
            <span>
              MAHJONG LEGEND <i>/</i> GAME STUDIO
            </span>
            <span>Versioned by design. Crafted with care.</span>
          </footer>
        </main>
      </div>
      {dialog && (
        <div className="modal-backdrop" role="presentation">
          <form
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="publish-title"
            onSubmit={(e) => void publishOrRollback(e)}
          >
            <div className="modal-title">
              <span className="empty-icon">
                <Icon name="releases" size={24} />
              </span>
              <button
                type="button"
                className="icon-button"
                aria-label="Close dialog"
                onClick={() => setDialog(null)}
              >
                <Icon name="close" />
              </button>
            </div>
            <p className="eyebrow">
              {dialog.kind === "publish" ? "PUBLISH DRAFT" : "ACTIVATE RELEASE"}
            </p>
            <h2 id="publish-title">
              {dialog.kind === "publish"
                ? "Make this release active?"
                : "Restore this release?"}
            </h2>
            <p>
              Ticket baru akan memakai{" "}
              {dialog.kind === "publish"
                ? draft?.name
                : dialog.release?.name || shorten(dialog.release?.id)}
              . Ronde yang sedang berjalan menyelesaikan snapshot sebelumnya.
            </p>
            <Field
              label="Alasan perubahan"
              hint="Disimpan dalam release history dan audit."
            >
              <textarea
                required
                minLength={3}
                maxLength={1000}
                rows={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                autoFocus
              />
            </Field>
            <div className="modal-actions">
              <button
                type="button"
                className="button"
                onClick={() => setDialog(null)}
              >
                Cancel
              </button>
              <button
                className="button gold"
                disabled={!!busy || reason.trim().length < 3}
              >
                {busy
                  ? "Processing…"
                  : dialog.kind === "publish"
                    ? "Publish release"
                    : "Activate release"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
function ValidationView({ validation }: { validation: Validation }) {
  return (
    <div className="validation-result">
      <Badge tone={validation.valid ? "jade" : "danger"}>
        {validation.valid ? "All checks passed" : "Action required"}
      </Badge>
      {validation.receipt?.hash && (
        <p className="hash">Receipt {validation.receipt.hash}</p>
      )}
      {validation.errors?.map((e, i) => (
        <div className="validation-item error" key={i}>
          <Icon name="close" size={16} />
          <span>
            {typeof e === "string"
              ? e
              : (e.field ? e.field + ": " : "") + e.message}
          </span>
        </div>
      ))}
      {validation.warnings?.map((e, i) => (
        <div className="validation-item" key={i}>
          <span className="warning-dot" />
          <span>{e}</span>
        </div>
      ))}
    </div>
  );
}
function Login({
  session,
  setupToken,
  error,
  busy,
  onLogin,
  onRetry,
}: {
  session: Session | null;
  setupToken: string;
  error: string;
  busy: string;
  onLogin: (data: Record<string, string>, setup: boolean) => Promise<void>;
  onRetry: () => void;
}) {
  const [username, setUsername] = useState(""),
    [password, setPassword] = useState(""),
    [token, setToken] = useState(setupToken);
  const setup = !!session?.setup_required;
  return (
    <div className="login-layout">
      <section className="login-art">
        <div className="brand">
          <span className="brand-mark">發</span>
          <span>
            MAHJONG LEGEND<small>GAME STUDIO</small>
          </span>
        </div>
        <div>
          <p className="eyebrow">A WORKSPACE FOR EVERY DETAIL</p>
          <h1>
            Shape the game.
            <br />
            <em>Craft the feeling.</em>
          </h1>
          <p>
            Rules, tiles, and sound.
            <br />
            One considered release at a time.
          </p>
          <div className="login-emblem">發</div>
        </div>
        <span className="small muted">
          PRIVATE WORKSPACE · VIRTUAL CREDIT GAME
        </span>
      </section>
      <section className="login-form-wrap">
        <form
          className="login-form"
          onSubmit={(e) => {
            e.preventDefault();
            void onLogin(
              setup ? { token, username, password } : { username, password },
              setup,
            );
          }}
        >
          <Badge tone="jade">
            {setup ? "First owner setup" : "Authorized access"}
          </Badge>
          <h2>
            {setup ? "Create your workspace owner." : "Welcome to Game Studio."}
          </h2>
          <p>
            {setup
              ? "Pilih akun owner untuk mengelola draft dan release. Setup token hanya digunakan sekali."
              : "Masuk untuk mengatur pengalaman Mahjong Legend Anda."}
          </p>
          {error && <Notice tone="danger">{error}</Notice>}
          {setup && (
            <Field label="Setup token">
              <input
                type="password"
                autoComplete="off"
                value={token}
                required
                onChange={(e) => setToken(e.target.value)}
              />
            </Field>
          )}
          <Field label="Username">
            <input
              autoComplete="username"
              autoCapitalize="none"
              value={username}
              required
              onChange={(e) => setUsername(e.target.value)}
            />
          </Field>
          <Field
            label="Password"
            hint={
              setup
                ? "Gunakan password unik yang kuat, minimum 12 karakter."
                : undefined
            }
          >
            <input
              type="password"
              autoComplete={setup ? "new-password" : "current-password"}
              value={password}
              minLength={setup ? 12 : undefined}
              required
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <button className="button primary full" disabled={!!busy || !session}>
            {busy
              ? "Connecting…"
              : setup
                ? "Create owner & sign in"
                : "Sign in"}
            <Icon name="chevron" size={17} />
          </button>
          {!session && (
            <button className="button full" type="button" onClick={onRetry}>
              Retry connection
            </button>
          )}
          <p className="login-security">
            <Icon name="shield" size={15} />
            Session protected · no public registration
          </p>
          <a className="text-button" href="/">
            ← Back to game
          </a>
        </form>
      </section>
    </div>
  );
}
function JobsTable({
  jobs,
  canTest,
  onCancel,
}: {
  jobs: Job[];
  canTest: boolean;
  onCancel: (id: string) => void;
}) {
  return (
    <Section
      eyebrow="WORKER QUEUE"
      title="Jobs & reports"
      description="Progress dan hasil berasal dari worker persisten."
    >
      {jobs.length ? (
        <div className="job-list">
          {jobs.map((job) => (
            <div className="job-row" key={job.id}>
              <div className="job-icon">
                <Icon
                  name={
                    job.kind?.includes("math") || job.kind?.includes("simulat")
                      ? "math"
                      : job.kind?.includes("audio")
                        ? "audio"
                        : "tiles"
                  }
                  size={21}
                />
              </div>
              <div className="job-info">
                <strong>{job.kind?.replace(/_/g, " ") || "Job"}</strong>
                <small>
                  {shorten(job.id)} · {formatDate(job.created_at)}
                </small>
                {typeof job.progress === "number" && (
                  <progress max={100} value={job.progress} />
                )}{" "}
                {job.error && <p className="danger-text small">{job.error}</p>}
                {job.result && Object.keys(job.result).length > 0 && (
                  <details>
                    <summary>View report</summary>
                    <pre>{JSON.stringify(job.result, null, 2)}</pre>
                  </details>
                )}
              </div>
              <Badge
                tone={
                  ["completed", "succeeded", "ready", "success"].includes(
                    job.status,
                  )
                    ? "jade"
                    : job.status === "failed"
                      ? "danger"
                      : "gold"
                }
              >
                {job.status}
              </Badge>
              {["queued", "pending", "running", "processing"].includes(
                job.status,
              ) && (
                <button
                  className="button small subtle"
                  disabled={!canTest}
                  onClick={() => onCancel(job.id)}
                >
                  Cancel
                </button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <Empty icon="math" title="Queue is clear">
          Render aset atau jalankan Math Lab untuk membuat job.
        </Empty>
      )}
    </Section>
  );
}
function MathLab({
  draft,
  jobs,
  canTest,
  busy,
  onSimulate,
  onCancel,
}: {
  draft: Draft | null;
  jobs: Job[];
  canTest: boolean;
  busy: boolean;
  onSimulate: (data: {
    rounds: number;
    seed_domain: string;
    target_rtp: number;
  }) => Promise<void>;
  onCancel: (id: string) => void;
}) {
  const [rounds, setRounds] = useState(1000),
    [domain, setDomain] = useState(
      "validation-" + new Date().toISOString().slice(0, 10),
    ),
    [target, setTarget] = useState(97);
  const relevant = jobs.filter(
    (j) => j.kind?.includes("math") || j.kind?.includes("simulat"),
  );
  const report = relevant.find(
    (j) => j.result && typeof j.result.rtp_percent === "number",
  )?.result;
  return (
    <>
      <Notice>
        Target RTP adalah sasaran evaluasi. Nilainya tidak mengubah probabilitas
        secara otomatis dan tidak membuktikan hasil game akan mencapai target.
      </Notice>
      <div className="two-column">
        <Section
          eyebrow="COMPLETE PAID ROUNDS"
          title="Run a simulation"
          description="Setiap sampel meliputi seluruh cascade, free spins, dan retrigger dari satu paid round."
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void onSimulate({
                rounds,
                seed_domain: domain,
                target_rtp: target,
              });
            }}
          >
            <div className="form-grid">
              <NumberField
                label="Paid rounds"
                value={rounds}
                min={100}
                max={1000000}
                step={100}
                onChange={setRounds}
              />
              <NumberField
                label="Target RTP · %"
                value={target}
                min={0}
                max={200}
                onChange={setTarget}
              />
            </div>
            <Field
              label="Seed domain"
              hint="Label eksperimen. Server menghasilkan dua domain seed independen; label ini tidak mengontrol RNG."
            >
              <input
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                required
                minLength={3}
                maxLength={120}
              />
            </Field>
            <button
              className="button primary full"
              disabled={!draft || !canTest || busy}
            >
              <Icon name="math" size={17} />
              Queue simulation
            </button>
          </form>
        </Section>
        <Section eyebrow="READ THE EVIDENCE" title="What the result means">
          <div className="explain-list">
            <div>
              <span>01</span>
              <p>
                <strong>RTP & uncertainty</strong>Estimasi dan interval berasal
                dari sampel. Sampel kecil belum mengukur rare event dengan
                presisi.
              </p>
            </div>
            <div>
              <span>02</span>
              <p>
                <strong>Hit frequency</strong>Positive payout berbeda dari
                return yang setidaknya menutup stake.
              </p>
            </div>
            <div>
              <span>03</span>
              <p>
                <strong>Reproducibility</strong>Report mencatat seed domain,
                snapshot config, dan engine version untuk pengulangan.
              </p>
            </div>
            <div>
              <span>04</span>
              <p>
                <strong>Publication gate</strong>Publish memeriksa report yang
                cocok dengan config math saat ini, bukan hasil draft lama.
              </p>
            </div>
          </div>
        </Section>
      </div>
      <>
        {report && (
          <Section eyebrow="LATEST COMPLETED REPORT" title="Measured outcome">
            <div className="metrics-grid simulation-metrics">
              <Metric
                label="Estimated RTP"
                value={Number(report.rtp_percent).toFixed(4) + "%"}
                detail={Number(report.rounds).toLocaleString() + " paid rounds"}
              />
              <Metric
                label="Positive payout"
                value={Number(report.positive_payout_percent).toFixed(3) + "%"}
              />
              <Metric
                label="Return ≥ stake"
                value={
                  Number(report.return_at_least_stake_percent).toFixed(3) + "%"
                }
              />
              <Metric
                label="Bonus entry"
                value={Number(report.bonus_entry_percent).toFixed(3) + "%"}
              />
            </div>
            {Array.isArray(report.rtp_ci95_percent) && (
              <div className="report-confidence">
                95% interval ·{" "}
                <strong>
                  {report.rtp_ci95_percent
                    .map((x) => Number(x).toFixed(4) + "%")
                    .join(" – ")}
                </strong>
                <br />
                Cap count: {String(report.cap_count ?? 0)} · Failures:{" "}
                {String(report.failures ?? 0)} ·{" "}
                {Number(report.rounds) < 100000
                  ? "Exploratory run; belum memenuhi gate publish changed math."
                  : "Publication gate tetap memeriksa hash dan hasil validasi."}
              </div>
            )}
            <p className="hash">
              Config {String(report.config_sha256 || "—")}
              <br />
              Engine {String(report.engine_sha256 || "—")}
            </p>
          </Section>
        )}
      </>
      <JobsTable jobs={relevant} canTest={canTest} onCancel={onCancel} />
    </>
  );
}
