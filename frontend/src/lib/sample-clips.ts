import type { Video } from "@/lib/api";

/**
 * Placeholder clips for the Explore page's layout/animation sections
 * (topic pills, grid, marquee) while no backend is connected. These are NOT
 * real uploaded content — thumbnail_url is always null so they render as the
 * plain gold placeholder tile, never a real thumbnail, and every screen that
 * uses this data labels it "Sample preview." The search bar at the top of
 * Explore never uses this file — it always calls the real `searchVideos` API.
 */
/**
 * Fields the deployed API supplies for real clips. Samples carry empty values
 * so nothing here can be mistaken for upstream data: no playlist to play, no
 * session to open, no uploader, and zero engagement counts.
 */
const NOT_FROM_API = {
  playlist_url: null,
  session_id: null,
  uploader: null,
  game: null,
  view_count: 0,
  like_count: 0,
  publish_state: null,
  published_at: null,
} as const;

type SampleClip = Omit<Video, keyof typeof NOT_FROM_API>;

export const SAMPLE_CLIPS: Video[] = ([
  {
    video_id: "sample-1",
    filename: "sample-1.mp4",
    title: "Speedrunning the nether portal",
    duration_seconds: 184,
    file_size_bytes: 0,
    upload_date: new Date().toISOString(),
    processing_status: "complete",
    processing_error: null,
    searchable: true,
    summary: null,
    topics: ["speedrun", "minecraft"],
    frame_count: 0,
    segment_count: 4,
    thumbnail_url: null,
  },
  {
    video_id: "sample-2",
    filename: "sample-2.mp4",
    title: "1v4 clutch in ranked",
    duration_seconds: 96,
    file_size_bytes: 0,
    upload_date: new Date().toISOString(),
    processing_status: "complete",
    processing_error: null,
    searchable: true,
    summary: null,
    topics: ["clutch", "ranked"],
    frame_count: 0,
    segment_count: 2,
    thumbnail_url: null,
  },
  {
    video_id: "sample-3",
    filename: "sample-3.mp4",
    title: "Base build timelapse",
    duration_seconds: 612,
    file_size_bytes: 0,
    upload_date: new Date().toISOString(),
    processing_status: "complete",
    processing_error: null,
    searchable: true,
    summary: null,
    topics: ["build", "minecraft"],
    frame_count: 0,
    segment_count: 9,
    thumbnail_url: null,
  },
  {
    video_id: "sample-4",
    filename: "sample-4.mp4",
    title: "Funny voice chat moment",
    duration_seconds: 42,
    file_size_bytes: 0,
    upload_date: new Date().toISOString(),
    processing_status: "complete",
    processing_error: null,
    searchable: true,
    summary: null,
    topics: ["funny", "voice chat"],
    frame_count: 0,
    segment_count: 1,
    thumbnail_url: null,
  },
  {
    video_id: "sample-5",
    filename: "sample-5.mp4",
    title: "Boss fight, first try",
    duration_seconds: 311,
    file_size_bytes: 0,
    upload_date: new Date().toISOString(),
    processing_status: "complete",
    processing_error: null,
    searchable: true,
    summary: null,
    topics: ["boss fight"],
    frame_count: 0,
    segment_count: 5,
    thumbnail_url: null,
  },
  {
    video_id: "sample-6",
    filename: "sample-6.mp4",
    title: "Redstone contraption explained",
    duration_seconds: 227,
    file_size_bytes: 0,
    upload_date: new Date().toISOString(),
    processing_status: "complete",
    processing_error: null,
    searchable: true,
    summary: null,
    topics: ["redstone", "minecraft"],
    frame_count: 0,
    segment_count: 3,
    thumbnail_url: null,
  },
] satisfies SampleClip[]).map((clip) => ({ ...clip, ...NOT_FROM_API }));
