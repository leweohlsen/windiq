/** Friendly aliases for the orval-generated API types. Hooks and fetchers
 * live in src/api/generated (npm run generate:api). */
export type {
  DailyPointOut as DailyPoint,
  IngestRunOut as IngestRun,
  MetricsOut as Metrics,
  PowerCurvePointOut as PowerCurvePoint,
  RoseSectorOut as RoseSector,
  TurbineDetailOut as TurbineDetail,
  WindOut as WindResponse,
} from "./api/generated/windIQAPI.schemas";
