/** #942 thin re-export path for launchers that still import TERMINAL_* names. */
export {
  PUBLIC_EXIT_CODES as TERMINAL_EXIT_CODES,
  PUBLIC_RUN_RESULTS as TERMINAL_EXIT_STATUSES,
  exitCodeForPublicResult as exitCodeForTerminal,
  exitProcessForFamilyRun,
  familyDriverExitCode,
  isPublicRunResult as isTerminalExitStatus,
  publicResultExitCode,
  runResultExitCode,
  type PublicRunResult as TerminalExitStatus,
} from "./publicResult.js";
