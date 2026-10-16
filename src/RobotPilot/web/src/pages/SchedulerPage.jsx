import React, {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { toast } from "react-toastify";

import { AuthContext } from "../app/App";
import { useT, T } from "../shared/i18n/i18n";
import { useRoleAccess } from "../shared/auth/roleAccess";
import { apiFetch } from "../shared/api/apiFetch";
import {
  backupLegacySchedules,
  createSchedule,
  deleteSchedule,
  fetchScheduleRuns,
  fetchSchedules,
  fetchSavedRoutes,
  getLegacySchedules,
  markLegacyScheduleImported,
  patchSchedule,
  saveRouteAsMission,
} from "../shared/schedules/schedules";
import {
  DashboardCard,
  EmptyState,
  SectionHeader,
} from "../shared/ui/Dashboard";
import Switcher from "../shared/ui/Switcher";

const inputClass =
  "rounded-lg border border-borderSubtle bg-bgCard px-3 py-2 text-sm text-textWhiteHover outline-none focus:border-themeBlue";
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const weekdayValue = (index) => (index + 1) % 7;
const dateToday = () => new Date().toLocaleDateString("en-CA");
const reusableTask = (mission) =>
  mission?.id &&
  mission?.name &&
  Array.isArray(mission.steps) &&
  mission.steps.length > 0 &&
  !String(mission.id).startsWith("manual-");

const fetchMissionNames = async (robotId) => {
  const response = await apiFetch(
    `/api/v1/robots/${encodeURIComponent(robotId)}/missions`,
    { cache: "no-store" },
  );
  const payload = await response.json();
  return Array.isArray(payload.missions) ? payload.missions : [];
};
const newForm = () => ({
  name: "",
  route_key: "",
  recurrence: "daily",
  local_time: "08:00",
  start_date: dateToday(),
  weekdays: [1, 2, 3, 4, 5],
});

const SchedulerPage = () => {
  const { t } = useT();
  const { robotId } = useContext(AuthContext);
  const access = useRoleAccess("Operator");
  const [schedules, setSchedules] = useState([]);
  const [missions, setMissions] = useState([]);
  const [savedRoutes, setSavedRoutes] = useState([]);
  const [legacy, setLegacy] = useState(getLegacySchedules);
  const [history, setHistory] = useState([]);
  const [form, setForm] = useState(newForm);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const timezone = useMemo(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    [],
  );

  const refresh = useCallback(async () => {
    if (!robotId) return;
    try {
      const [nextSchedules, nextRoutes, nextMissions] = await Promise.all([
        fetchSchedules(robotId),
        fetchSavedRoutes(robotId),
        fetchMissionNames(robotId),
      ]);
      setSchedules(nextSchedules);
      setSavedRoutes(nextRoutes);
      setMissions(nextMissions);
      setLoading(false);
    } catch (error) {
      setLoading(false);
      toast.error(error.message || t("Could not load schedules"));
    }
  }, [robotId, t]);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    setForm((current) =>
      current.route_key &&
      !savedRoutes.some((route) => route.route_key === current.route_key)
        ? { ...current, route_key: "" }
        : current,
    );
  }, [savedRoutes]);

  useEffect(() => {
    let cancelled = false;
    if (robotId && schedules.length) {
      Promise.all(
        schedules.map((schedule) =>
          fetchScheduleRuns(robotId, schedule.schedule_id).catch(() => []),
        ),
      ).then((rows) => {
        if (!cancelled) setHistory(rows.flat());
      });
    } else setHistory([]);
    return () => {
      cancelled = true;
    };
  }, [robotId, schedules]);

  const mutate = async (callback) => {
    if (!access.allowed || busy) return;
    setBusy(true);
    try {
      await callback();
      await refresh();
    } catch (error) {
      toast.error(error.message || t("Schedule operation failed"));
    } finally {
      setBusy(false);
    }
  };

  const add = (event) => {
    event.preventDefault();
    const selectedRoute = savedRoutes.find(
      (route) => route.route_key === form.route_key,
    );
    if (
      !form.name.trim() ||
      !selectedRoute
    ) return;
    const scheduleFields = { ...form };
    delete scheduleFields.route_key;
    const schedule = {
      ...scheduleFields,
      name: form.name.trim(),
      timezone,
      enabled: true,
      start_date: form.recurrence === "once" ? form.start_date : null,
      weekdays: form.recurrence === "weekly" ? form.weekdays : [],
    };
    mutate(async () => {
      schedule.mission_id = await saveRouteAsMission(robotId, selectedRoute);
      await createSchedule(robotId, schedule);
      setForm(newForm());
    });
  };

  const importableLegacy = legacy.filter(
    (item) =>
      item?.action?.type === "mission" &&
      item.repeat === "daily" &&
      missions.some((mission) => reusableTask(mission) && mission.id === item.action.missionId),
  );

  const importLegacy = () =>
    mutate(async () => {
      backupLegacySchedules();
      let imported = 0;
      for (const item of importableLegacy) {
        await createSchedule(robotId, {
          name: String(item.name || "Imported schedule").slice(0, 120),
          mission_id: String(item.action.missionId),
          recurrence: "daily",
          timezone,
          local_time: item.time,
          start_date: null,
          weekdays: [],
          enabled: Boolean(item.enabled),
        });
        markLegacyScheduleImported(item.id);
        imported += 1;
      }
      setLegacy(getLegacySchedules());
      toast.success(`${t("Imported schedules")}: ${imported}`);
    });

  const missionName = (id) =>
    missions.find((mission) => mission.id === id)?.name || id;
  const describeHistory = (run) =>
    `${run.status}${run.task_id ? ` · ${run.task_id}` : ""}${
      run.reason ? ` · ${run.reason}` : ""
    }`;

  return (
    <div className="sectionHeight space-y-5 py-4 sm:py-6">
      <SectionHeader
        eyebrow="Autonomy"
        title="Scheduler"
        description="Schedules are stored and triggered by the robot. The robot checks stop state, task activity and map binding before each run."
      />

      <DashboardCard className="p-0">
        {loading ? (
          <p className="p-4 text-sm text-themeTextGray">
            <T>{"Loading schedules"}</T>
          </p>
        ) : schedules.length === 0 ? (
          <EmptyState
            title="No schedules"
            description="Add a mission schedule below."
          />
        ) : (
          <ul className="divide-y divide-borderSubtle/30 font-[RobotoMono]">
            {schedules.map((schedule) => {
              const runs = history
                .filter((run) => run.schedule_id === schedule.schedule_id)
                .slice(0, 3);
              return (
                <li
                  key={schedule.schedule_id}
                  className="flex flex-wrap items-start gap-3 px-4 py-3"
                >
                  <span className="w-14 shrink-0 pt-1 text-lg font-semibold text-themeBlue">
                    {schedule.local_time}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-textWhiteHover">
                      {schedule.name}
                    </p>
                    <p className="text-xs text-themeTextGray">
                      {t("Mission:")} {missionName(schedule.mission_id)} ·{" "}
                      {schedule.recurrence} · {schedule.timezone}
                      {schedule.recurrence === "once"
                        ? ` · ${schedule.start_date}`
                        : ""}
                    </p>
                    <p className="text-[11px] text-themeTextGray/80">
                      <T>{"Next run"}</T>: {schedule.next_run_at || t("None")}
                    </p>
                    {runs.map((run) => (
                      <p
                        key={run.run_id || run.scheduled_for}
                        className="text-[11px] text-themeTextGray/70"
                      >
                        {run.scheduled_for} · {describeHistory(run)}
                      </p>
                    ))}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Switcher
                      switcherValue={Boolean(schedule.enabled)}
                      onChange={(enabled) =>
                        mutate(() =>
                          patchSchedule(robotId, schedule, { enabled }),
                        )
                      }
                    />
                    <span
                      className={`text-xs ${
                        schedule.enabled
                          ? "text-statusGreen"
                          : "text-themeTextGray"
                      }`}
                    >
                      {t(schedule.enabled ? "Enabled" : "Disabled")}
                    </span>
                  </div>
                  <button
                    type="button"
                    disabled={!access.allowed || busy}
                    onClick={() =>
                      mutate(() => deleteSchedule(robotId, schedule))
                    }
                    aria-label={`${t("Delete")} ${schedule.name}`}
                    className="px-1 text-themeTextGray hover:text-statusRed disabled:opacity-40"
                  >
                    ×
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </DashboardCard>

      <DashboardCard className="p-4 font-[RobotoMono]">
        <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.14em] text-themeBlue">
          <T>{"Add schedule"}</T>
        </p>
        <form
          onSubmit={add}
          className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4"
        >
          <input
            className={inputClass}
            value={form.name}
            onChange={(e) =>
              setForm((prev) => ({ ...prev, name: e.target.value }))
            }
            placeholder={t("Name (e.g. Nightly dock)")}
          />
          <select
            className={inputClass}
            value={form.route_key}
            onChange={(e) =>
              setForm((prev) => ({ ...prev, route_key: e.target.value }))
            }
            required
          >
            <option value="">{t("Select a saved task…")}</option>
            {savedRoutes.map((route) => (
                <option key={route.route_key} value={route.route_key}>
                  {route.map} / {route.name}
                </option>
              ))}
          </select>
          <select
            className={inputClass}
            value={form.recurrence}
            onChange={(e) =>
              setForm((prev) => ({ ...prev, recurrence: e.target.value }))
            }
          >
            <option value="daily">{t("Daily")}</option>
            <option value="weekly">{t("Weekly")}</option>
            <option value="once">{t("Once")}</option>
          </select>
          <input
            className={inputClass}
            type="time"
            value={form.local_time}
            onChange={(e) =>
              setForm((prev) => ({ ...prev, local_time: e.target.value }))
            }
            required
          />
          {form.recurrence === "once" && (
            <input
              className={inputClass}
              type="date"
              min={dateToday()}
              value={form.start_date}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, start_date: e.target.value }))
              }
              required
            />
          )}
          {form.recurrence === "weekly" && (
            <div className="flex flex-wrap gap-2 lg:col-span-2">
              {WEEKDAYS.map((day, index) => {
                const value = weekdayValue(index);
                const checked = form.weekdays.includes(value);
                return (
                  <label
                    key={day}
                    className="flex items-center gap-1 rounded-lg border border-borderSubtle px-2 py-1 text-xs"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() =>
                        setForm((prev) => ({
                          ...prev,
                          weekdays: checked
                            ? prev.weekdays.filter((item) => item !== value)
                            : [...prev.weekdays, value].sort(),
                        }))
                      }
                    />
                    {t(day)}
                  </label>
                );
              })}
            </div>
          )}
          <button
            type="submit"
            disabled={!access.allowed || busy || !savedRoutes.length}
            className="rounded-lg border border-themeBlue bg-themeBlue/10 px-4 py-2 text-sm font-semibold text-themeBlue transition-colors hover:bg-themeBlue hover:text-white disabled:opacity-40"
          >
            <T>{"Add"}</T>
          </button>
        </form>
        {!savedRoutes.length && !loading && (
          <p className="mt-2 text-xs text-themeTextGray">
            {t("No routes have been saved in Task planning.")}
          </p>
        )}
        {savedRoutes.length > 0 && (
          <p className="mt-2 text-xs text-themeTextGray">
            {t("A schedule uses the saved route as it exists when the schedule is created. Recreate the schedule after editing that route.")}
          </p>
        )}
        <p className="mt-2 text-[11px] text-themeTextGray/70">
          <T>{"Robot time zone"}</T>: {timezone}
        </p>
        {!access.allowed && (
          <p className="mt-2 text-xs text-statusYellow">{t(access.reason)}</p>
        )}
      </DashboardCard>

      {legacy.length > 0 && (
        <DashboardCard className="space-y-2 p-4">
          <p className="font-semibold">
            <T>{"Legacy browser schedules found"}</T>: {legacy.length}
          </p>
          <p className="text-xs text-themeTextGray">
            <T>
              {
                "Legacy schedules never run in this browser. Supported daily mission schedules can be imported; other entries remain in the saved backup for manual review."
              }
            </T>
          </p>
          <p className="text-xs text-themeTextGray">
            <T>{"Can import"}</T>: {importableLegacy.length} ·{" "}
            <T>{"Requires manual review"}</T>:{" "}
            {legacy.length - importableLegacy.length}
          </p>
          <button
            type="button"
            disabled={!access.allowed || busy || !importableLegacy.length}
            onClick={importLegacy}
            className="rounded-lg border border-themeBlue px-3 py-2 text-sm text-themeBlue disabled:opacity-40"
          >
            <T>{"Back up and import supported schedules"}</T>
          </button>
        </DashboardCard>
      )}
    </div>
  );
};

export default SchedulerPage;
