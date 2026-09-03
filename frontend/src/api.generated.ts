// OpenAPI-SHA256: 512498d3d23e02b67d22fccf62411596c2c6a9f7061c69d7561c59916eeebd86
export interface paths {
    "/api/ai/models": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** List Ai Models */
        post: operations["list_ai_models_api_ai_models_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/ai/test": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Test Ai Connection */
        post: operations["test_ai_connection_api_ai_test_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Jobs */
        get: operations["list_jobs_api_jobs_get"];
        put?: never;
        /** Create Job */
        post: operations["create_job_api_jobs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/frame-suggestion": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Suggest Frame Count */
        post: operations["suggest_frame_count_api_jobs_frame_suggestion_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Job */
        get: operations["get_job_api_jobs__job_id__get"];
        put?: never;
        post?: never;
        /** Delete Job */
        delete: operations["delete_job_api_jobs__job_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/activity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Job Activity */
        get: operations["get_job_activity_api_jobs__job_id__activity_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/assets/{asset_path}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Asset */
        get: operations["get_asset_api_jobs__job_id__assets__asset_path__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancel Job */
        post: operations["cancel_job_api_jobs__job_id__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/diagnostics.zip": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Download Diagnostics Zip */
        get: operations["download_diagnostics_zip_api_jobs__job_id__diagnostics_zip_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/download.zip": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Download Zip */
        get: operations["download_zip_api_jobs__job_id__download_zip_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/finalize": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Finalize Job */
        post: operations["finalize_job_api_jobs__job_id__finalize_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/frame-candidates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Frame Candidates */
        get: operations["get_frame_candidates_api_jobs__job_id__frame_candidates_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/frame-candidates/{candidate_id}/reject": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reject Job Frame Candidate */
        post: operations["reject_job_frame_candidate_api_jobs__job_id__frame_candidates__candidate_id__reject_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/frame-candidates/{candidate_id}/select": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Select Job Frame Candidate */
        post: operations["select_job_frame_candidate_api_jobs__job_id__frame_candidates__candidate_id__select_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/note-chunks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Note Chunks */
        get: operations["list_note_chunks_api_jobs__job_id__note_chunks_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/note-chunks/{chunk_id}/regenerate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Regenerate Note Chunk */
        post: operations["regenerate_note_chunk_api_jobs__job_id__note_chunks__chunk_id__regenerate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/note-versions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Note Versions */
        get: operations["list_note_versions_api_jobs__job_id__note_versions_get"];
        put?: never;
        /** Regenerate Note Version Endpoint */
        post: operations["regenerate_note_version_endpoint_api_jobs__job_id__note_versions_post"];
        delete?: never;
        options?: never;
        head?: never;
        /** Update Note Version Selection */
        patch: operations["update_note_version_selection_api_jobs__job_id__note_versions_patch"];
        trace?: never;
    };
    "/api/jobs/{job_id}/preview/note": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Preview Note */
        get: operations["preview_note_api_jobs__job_id__preview_note_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/preview/note/{version_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Preview Note Version */
        get: operations["preview_note_version_api_jobs__job_id__preview_note__version_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/preview/subtitles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Preview Subtitles */
        get: operations["preview_subtitles_api_jobs__job_id__preview_subtitles_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/quality-report": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Quality Report */
        get: operations["get_quality_report_api_jobs__job_id__quality_report_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/review-assets/prepare": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Prepare Job Review Assets */
        post: operations["prepare_job_review_assets_api_jobs__job_id__review_assets_prepare_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/review-draft": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Job Review Draft */
        get: operations["get_job_review_draft_api_jobs__job_id__review_draft_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/review-draft/paragraphs/{paragraph_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Update Job Review Draft Paragraph */
        patch: operations["update_job_review_draft_paragraph_api_jobs__job_id__review_draft_paragraphs__paragraph_id__patch"];
        trace?: never;
    };
    "/api/jobs/{job_id}/storage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Job Storage */
        get: operations["get_job_storage_api_jobs__job_id__storage_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/subtitles/confirm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Confirm Subtitles */
        post: operations["confirm_subtitles_api_jobs__job_id__subtitles_confirm_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/subtitles/regenerate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Regenerate Subtitles */
        post: operations["regenerate_subtitles_api_jobs__job_id__subtitles_regenerate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/transcript-corrections": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Transcript Correction Endpoint */
        post: operations["create_transcript_correction_endpoint_api_jobs__job_id__transcript_corrections_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/transcript-corrections/apply": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Apply Transcript Correction Endpoint */
        post: operations["apply_transcript_correction_endpoint_api_jobs__job_id__transcript_corrections_apply_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/transcription/cache": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Transcription Cache */
        delete: operations["delete_transcription_cache_api_jobs__job_id__transcription_cache_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/transcription/resume": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Resume Transcription */
        post: operations["resume_transcription_api_jobs__job_id__transcription_resume_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/models/faster-whisper/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Download Faster Whisper Model Endpoint */
        post: operations["download_faster_whisper_model_endpoint_api_models_faster_whisper_download_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/models/faster-whisper/download/{model_name}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Faster Whisper Model Download */
        get: operations["get_faster_whisper_model_download_api_models_faster_whisper_download__model_name__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ready */
        get: operations["ready_api_ready_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runtime": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Runtime */
        get: operations["runtime_api_runtime_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runtime/cuda-dependencies/install": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Cuda Dependency Install */
        get: operations["get_cuda_dependency_install_api_runtime_cuda_dependencies_install_get"];
        put?: never;
        /** Install Cuda Dependencies */
        post: operations["install_cuda_dependencies_api_runtime_cuda_dependencies_install_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runtime/faster-whisper/cache/clear": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Clear Faster Whisper Cache */
        post: operations["clear_faster_whisper_cache_api_runtime_faster_whisper_cache_clear_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runtime/local-dependencies/install": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Local Dependency Install */
        get: operations["get_local_dependency_install_api_runtime_local_dependencies_install_get"];
        put?: never;
        /** Install Local Dependencies */
        post: operations["install_local_dependencies_api_runtime_local_dependencies_install_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Settings */
        get: operations["get_settings_api_settings_get"];
        put?: never;
        post?: never;
        /** Delete Settings */
        delete: operations["delete_settings_api_settings_delete"];
        options?: never;
        head?: never;
        /** Update Settings */
        patch: operations["update_settings_api_settings_patch"];
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AIConnectionTestRequest */
        AIConnectionTestRequest: {
            /** Api Key */
            api_key: string;
            /** Base Url */
            base_url: string;
            /**
             * Max Output Tokens
             * @default 8192
             */
            max_output_tokens: number;
            /** Model */
            model: string;
            /** @default openai_chat_completions */
            protocol: components["schemas"]["AIProtocol"];
            /**
             * Thinking Enabled
             * @default false
             */
            thinking_enabled: boolean;
        };
        /** AIConnectionTestResponse */
        AIConnectionTestResponse: {
            /** Elapsed Ms */
            elapsed_ms: number;
            /**
             * Json Valid
             * @default false
             */
            json_valid: boolean;
            /** Model */
            model: string;
            /**
             * Ok
             * @default true
             */
            ok: boolean;
            protocol: components["schemas"]["AIProtocol"];
            /** Response Length */
            response_length: number;
        };
        /** AIModelInfo */
        AIModelInfo: {
            /** Display Name */
            display_name: string;
            /** Id */
            id: string;
            /** Owned By */
            owned_by?: string | null;
        };
        /** AIModelListRequest */
        AIModelListRequest: {
            /** Api Key */
            api_key: string;
            /** Base Url */
            base_url: string;
            /** @default openai_chat_completions */
            protocol: components["schemas"]["AIProtocol"];
        };
        /** AIModelListResponse */
        AIModelListResponse: {
            /** Models */
            models?: components["schemas"]["AIModelInfo"][];
        };
        /**
         * AIProtocol
         * @enum {string}
         */
        AIProtocol: "openai_chat_completions" | "openai_responses" | "anthropic_messages";
        /** Artifact */
        Artifact: {
            /** Asset Url */
            asset_url: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "audio" | "subtitle" | "markdown" | "image" | "json" | "zip" | "log";
            /** Label */
            label: string;
            /** Path */
            path: string;
        };
        /** Body_confirm_subtitles_api_jobs__job_id__subtitles_confirm_post */
        Body_confirm_subtitles_api_jobs__job_id__subtitles_confirm_post: {
            /**
             * Extras
             * @default
             */
            extras: string;
            /**
             * Frame Limit
             * @default 6
             */
            frame_limit: number;
            /**
             * Note Api Key
             * @default
             */
            note_api_key: string;
            /** @default openai_chat_completions */
            note_api_protocol: components["schemas"]["AIProtocol"];
            /**
             * Note Base Url
             * @default https://api.openai.com/v1
             */
            note_base_url: string;
            /**
             * Note Context Window Tokens
             * @default 32768
             */
            note_context_window_tokens: number;
            note_language: components["schemas"]["NoteLanguage"];
            /**
             * Note Max Output Tokens
             * @default 8192
             */
            note_max_output_tokens: number;
            /**
             * Note Model
             * @default gpt-5.5
             */
            note_model: string;
            /** @default detailed */
            note_style: components["schemas"]["NoteStyle"];
            /**
             * Note Thinking Enabled
             * @default false
             */
            note_thinking_enabled: boolean;
        };
        /** Body_create_job_api_jobs_post */
        Body_create_job_api_jobs_post: {
            /**
             * Extras
             * @default
             */
            extras: string;
            /**
             * Frame Limit
             * @default 6
             */
            frame_limit: number;
            /**
             * Local Whisper Compute Type
             * @default
             */
            local_whisper_compute_type: string;
            /**
             * Local Whisper Device
             * @default
             */
            local_whisper_device: string;
            /** @default openai_chat_completions */
            note_api_protocol: components["schemas"]["AIProtocol"];
            /**
             * Note Base Url
             * @default https://api.openai.com/v1
             */
            note_base_url: string;
            /**
             * Note Context Window Tokens
             * @default 32768
             */
            note_context_window_tokens: number;
            note_language: components["schemas"]["NoteLanguage"];
            /**
             * Note Max Output Tokens
             * @default 8192
             */
            note_max_output_tokens: number;
            /**
             * Note Model
             * @default gpt-5.5
             */
            note_model: string;
            /** @default detailed */
            note_style: components["schemas"]["NoteStyle"];
            /**
             * Note Thinking Enabled
             * @default false
             */
            note_thinking_enabled: boolean;
            /** @default balanced */
            performance_mode: components["schemas"]["PerformanceMode"];
            /** Subtitle */
            subtitle?: string | null;
            /**
             * Transcription Api Key
             * @default
             */
            transcription_api_key: string;
            /**
             * Transcription Base Url
             * @default https://api.openai.com/v1
             */
            transcription_base_url: string;
            /** @default auto */
            transcription_language: components["schemas"]["TranscriptionLanguage"];
            /** @default audio_transcriptions */
            transcription_mode: components["schemas"]["TranscriptionMode"];
            /**
             * Transcription Model
             * @default whisper-1
             */
            transcription_model: string;
            /**
             * Video
             * Format: binary
             */
            video: string;
        };
        /** Body_regenerate_note_chunk_api_jobs__job_id__note_chunks__chunk_id__regenerate_post */
        Body_regenerate_note_chunk_api_jobs__job_id__note_chunks__chunk_id__regenerate_post: {
            /**
             * Extras
             * @default
             */
            extras: string;
            /**
             * Frame Limit
             * @default 6
             */
            frame_limit: number;
            /** Note Api Key */
            note_api_key: string;
            /** @default openai_chat_completions */
            note_api_protocol: components["schemas"]["AIProtocol"];
            /**
             * Note Base Url
             * @default https://api.openai.com/v1
             */
            note_base_url: string;
            /**
             * Note Context Window Tokens
             * @default 32768
             */
            note_context_window_tokens: number;
            /** @default zh */
            note_language: components["schemas"]["NoteLanguage"];
            /**
             * Note Max Output Tokens
             * @default 8192
             */
            note_max_output_tokens: number;
            /**
             * Note Model
             * @default gpt-5.5
             */
            note_model: string;
            /** @default detailed */
            note_style: components["schemas"]["NoteStyle"];
            /**
             * Note Thinking Enabled
             * @default false
             */
            note_thinking_enabled: boolean;
        };
        /** Body_regenerate_note_version_endpoint_api_jobs__job_id__note_versions_post */
        Body_regenerate_note_version_endpoint_api_jobs__job_id__note_versions_post: {
            /**
             * Extras
             * @default
             */
            extras: string;
            /**
             * Frame Limit
             * @default 6
             */
            frame_limit: number;
            /**
             * Note Api Key
             * @default
             */
            note_api_key: string;
            /** @default openai_chat_completions */
            note_api_protocol: components["schemas"]["AIProtocol"];
            /**
             * Note Base Url
             * @default https://api.openai.com/v1
             */
            note_base_url: string;
            /**
             * Note Context Window Tokens
             * @default 32768
             */
            note_context_window_tokens: number;
            note_language: components["schemas"]["NoteLanguage"];
            /**
             * Note Max Output Tokens
             * @default 8192
             */
            note_max_output_tokens: number;
            /**
             * Note Model
             * @default gpt-5.5
             */
            note_model: string;
            /** @default detailed */
            note_style: components["schemas"]["NoteStyle"];
            /**
             * Note Thinking Enabled
             * @default false
             */
            note_thinking_enabled: boolean;
        };
        /** Body_regenerate_subtitles_api_jobs__job_id__subtitles_regenerate_post */
        Body_regenerate_subtitles_api_jobs__job_id__subtitles_regenerate_post: {
            /**
             * Local Whisper Compute Type
             * @default
             */
            local_whisper_compute_type: string;
            /**
             * Local Whisper Device
             * @default
             */
            local_whisper_device: string;
            /** @default balanced */
            performance_mode: components["schemas"]["PerformanceMode"];
            /**
             * Transcription Api Key
             * @default
             */
            transcription_api_key: string;
            /**
             * Transcription Base Url
             * @default https://api.openai.com/v1
             */
            transcription_base_url: string;
            /** @default auto */
            transcription_language: components["schemas"]["TranscriptionLanguage"];
            /** @default audio_transcriptions */
            transcription_mode: components["schemas"]["TranscriptionMode"];
            /**
             * Transcription Model
             * @default whisper-1
             */
            transcription_model: string;
        };
        /** Body_suggest_frame_count_api_jobs_frame_suggestion_post */
        Body_suggest_frame_count_api_jobs_frame_suggestion_post: {
            /**
             * Extras
             * @default
             */
            extras: string;
            /**
             * Local Whisper Compute Type
             * @default
             */
            local_whisper_compute_type: string;
            /**
             * Local Whisper Device
             * @default
             */
            local_whisper_device: string;
            /**
             * Note Api Key
             * @default
             */
            note_api_key: string;
            /** @default openai_chat_completions */
            note_api_protocol: components["schemas"]["AIProtocol"];
            /**
             * Note Base Url
             * @default https://api.openai.com/v1
             */
            note_base_url: string;
            /**
             * Note Context Window Tokens
             * @default 32768
             */
            note_context_window_tokens: number;
            note_language: components["schemas"]["NoteLanguage"];
            /**
             * Note Max Output Tokens
             * @default 8192
             */
            note_max_output_tokens: number;
            /**
             * Note Model
             * @default gpt-5.5
             */
            note_model: string;
            /** @default detailed */
            note_style: components["schemas"]["NoteStyle"];
            /**
             * Note Thinking Enabled
             * @default false
             */
            note_thinking_enabled: boolean;
            /** @default balanced */
            performance_mode: components["schemas"]["PerformanceMode"];
            /**
             * Transcription Api Key
             * @default
             */
            transcription_api_key: string;
            /**
             * Transcription Base Url
             * @default https://api.openai.com/v1
             */
            transcription_base_url: string;
            /** @default auto */
            transcription_language: components["schemas"]["TranscriptionLanguage"];
            /** @default audio_transcriptions */
            transcription_mode: components["schemas"]["TranscriptionMode"];
            /**
             * Transcription Model
             * @default whisper-1
             */
            transcription_model: string;
            /**
             * Video
             * Format: binary
             */
            video: string;
        };
        /** ChapterQualityReport */
        ChapterQualityReport: {
            /** Chapter Index */
            chapter_index: number;
            /** End Time */
            end_time: number;
            /** Issues */
            issues?: string[];
            /** Note Chars */
            note_chars: number;
            /** Selected Frame Count */
            selected_frame_count: number;
            /** Start Time */
            start_time: number;
            /** Title */
            title: string;
            /** Transcript Chars */
            transcript_chars: number;
        };
        /** CudaDependencyInstallState */
        CudaDependencyInstallState: {
            /**
             * Error
             * @default
             */
            error: string;
            /**
             * Progress
             * @default 0
             */
            progress: number;
            /**
             * Python Path
             * @default
             */
            python_path: string;
            /**
             * Status
             * @default idle
             * @enum {string}
             */
            status: "idle" | "pending" | "running" | "succeeded" | "failed";
        };
        /** FFmpegRuntimeStatus */
        FFmpegRuntimeStatus: {
            /** Available */
            available: boolean;
            /** Install Hint */
            install_hint: string;
            /** Path */
            path?: string | null;
        };
        /** FailureContext */
        FailureContext: {
            /** Attempt */
            attempt?: number | null;
            /** Context */
            context?: string | null;
            /** Error Code */
            error_code?: string | null;
            /** Finish Reason */
            finish_reason?: string | null;
            /** Flagged Categories */
            flagged_categories?: string[];
            /** Max Tokens */
            max_tokens?: number | null;
            /** Message */
            message?: string | null;
            /** Message Chars */
            message_chars?: number | null;
            /** Note Base Url */
            note_base_url?: string | null;
            /** Note Model */
            note_model?: string | null;
            /** Response File */
            response_file?: string | null;
            /** Response Length */
            response_length?: number | null;
            /** Stage */
            stage?: string | null;
            /** Status Code */
            status_code?: number | null;
            /** Summary */
            summary?: string | null;
            /** Ts */
            ts?: string | null;
        };
        /** FasterWhisperRuntimeStatus */
        FasterWhisperRuntimeStatus: {
            /** Available */
            available: boolean;
            /** Ctranslate2 Available */
            ctranslate2_available: boolean;
            /** Ctranslate2 Version */
            ctranslate2_version: string;
            /** Cuda Available */
            cuda_available: boolean;
            /** Cuda Device Count */
            cuda_device_count?: number | null;
            /** Cuda Dll Dirs */
            cuda_dll_dirs?: string[];
            /** Cuda Error */
            cuda_error: string;
            /** Cuda Runtime Available */
            cuda_runtime_available: boolean;
            /** Cuda Runtime Hint */
            cuda_runtime_hint: string;
            /**
             * Cuda Source
             * @enum {string}
             */
            cuda_source: "internal" | "external";
            /** External Python Error */
            external_python_error: string;
            /** External Python Path */
            external_python_path?: string | null;
            /**
             * External Python Source
             * @enum {string}
             */
            external_python_source: "environment" | "settings" | "default" | "missing";
            /** External Worker Available */
            external_worker_available: boolean;
            /** External Worker Path */
            external_worker_path: string;
            /** Import Error */
            import_error: string;
            /** Install Hint */
            install_hint: string;
            /** Internal Available */
            internal_available: boolean;
            /** Internal Import Error */
            internal_import_error: string;
            /** Model Available */
            model_available: boolean;
            /** Python Available */
            python_available: boolean;
            /**
             * Python Package Install Mode
             * @enum {string}
             */
            python_package_install_mode: "default" | "user";
            /** Ready For Cpu */
            ready_for_cpu: boolean;
            /** Ready For Cuda */
            ready_for_cuda: boolean;
            /** Worker Error */
            worker_error: string;
            /** Worker Error Code */
            worker_error_code: string;
            /** Worker Probe Error */
            worker_probe_error: string;
            /** Worker Ready */
            worker_ready: boolean;
        };
        /** FrameCandidate */
        FrameCandidate: {
            /** Anchor Time */
            anchor_time?: number | null;
            /** Bright Ratio */
            bright_ratio?: number | null;
            /** Brightness */
            brightness?: number | null;
            /** Chapter Index */
            chapter_index: number;
            /** Contrast */
            contrast?: number | null;
            /** Dark Ratio */
            dark_ratio?: number | null;
            /** Duplicate Of */
            duplicate_of?: string | null;
            /** Hash */
            hash: string;
            /** Id */
            id: string;
            /**
             * Note Excerpt
             * @default
             */
            note_excerpt: string;
            /** Path */
            path: string;
            /**
             * Quality Score
             * @default 0.5
             */
            quality_score: number;
            /** Reason */
            reason: string;
            /**
             * Rejected
             * @default false
             */
            rejected: boolean;
            /** Risk Flags */
            risk_flags?: string[];
            /**
             * Scene Sample Count
             * @default 0
             */
            scene_sample_count: number;
            /**
             * Selected
             * @default false
             */
            selected: boolean;
            /** Sharpness */
            sharpness?: number | null;
            /** Similarity */
            similarity: number;
            /**
             * Source
             * @enum {string}
             */
            source: "note_key_moment" | "chapter_fallback";
            /**
             * Stability Score
             * @default 0.5
             */
            stability_score: number;
            /**
             * Subtitle Excerpt
             * @default
             */
            subtitle_excerpt: string;
            /** Time */
            time: number;
            /**
             * Time Offset
             * @default 0
             */
            time_offset: number;
            /**
             * Transition Score
             * @default 0
             */
            transition_score: number;
        };
        /** FrameCandidateChapterContext */
        FrameCandidateChapterContext: {
            /** Chapter Index */
            chapter_index: number;
            /** End Time */
            end_time: number;
            /**
             * Note Excerpt
             * @default
             */
            note_excerpt: string;
            /** Start Time */
            start_time: number;
            /**
             * Subtitle Excerpt
             * @default
             */
            subtitle_excerpt: string;
            /** Title */
            title: string;
        };
        /** FrameCandidateIndex */
        FrameCandidateIndex: {
            /** Candidates */
            candidates?: components["schemas"]["FrameCandidate"][];
            /** Chapter Contexts */
            chapter_contexts?: components["schemas"]["FrameCandidateChapterContext"][];
        };
        /** FrameSuggestion */
        FrameSuggestion: {
            /** Candidate Count */
            candidate_count: number;
            /** Reasons */
            reasons?: string[];
            /** Recommended Frame Count */
            recommended_frame_count: number;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HealthState */
        HealthState: {
            /** Ffmpeg Available */
            ffmpeg_available: boolean;
            /** Ffmpeg Path */
            ffmpeg_path?: string | null;
            /** Ok */
            ok: boolean;
            runtime: components["schemas"]["RuntimeState"];
            /** Runtime Ok */
            runtime_ok: boolean;
        };
        /** JobActivityEvent */
        JobActivityEvent: {
            /**
             * Context
             * @default
             */
            context: string;
            /**
             * Level
             * @default INFO
             */
            level: string;
            /** Message */
            message: string;
            /** Stage */
            stage: string;
            /** Summary */
            summary: string;
            /** Timestamp */
            timestamp: string;
        };
        /** JobActivitySnapshot */
        JobActivitySnapshot: {
            /**
             * Binary Split Count
             * @default 0
             */
            binary_split_count: number;
            /**
             * Current Context
             * @default
             */
            current_context: string;
            /** Events */
            events?: components["schemas"]["JobActivityEvent"][];
            /**
             * Format Failure Count
             * @default 0
             */
            format_failure_count: number;
            /** Job Id */
            job_id: string;
            /**
             * Request Count
             * @default 0
             */
            request_count: number;
            /**
             * Response Count
             * @default 0
             */
            response_count: number;
            /**
             * Truncation Retry Count
             * @default 0
             */
            truncation_retry_count: number;
        };
        /** JobHistory */
        JobHistory: {
            /** Jobs */
            jobs?: components["schemas"]["JobSummary"][];
        };
        /** JobPublicState */
        JobPublicState: {
            /**
             * Artifact Revision
             * @default
             */
            artifact_revision: string;
            /** Artifacts */
            artifacts?: components["schemas"]["Artifact"][];
            /** Download Filename */
            download_filename?: string | null;
            /** Error */
            error?: string | null;
            failure_context?: components["schemas"]["FailureContext"] | null;
            /** Job Id */
            job_id: string;
            /** Progress */
            progress: number;
            /** @default queued */
            stage: components["schemas"]["JobStage"];
            /**
             * Stage Elapsed Seconds
             * @default 0
             */
            stage_elapsed_seconds: number;
            /**
             * State Revision
             * @default 0
             */
            state_revision: number;
            status: components["schemas"]["JobStatus"];
            /** Step */
            step: string;
            /** Step Started At */
            step_started_at?: string | null;
            /** Updated At */
            updated_at?: string | null;
            work_progress?: components["schemas"]["TranscriptionWorkProgress"] | null;
        };
        /**
         * JobStage
         * @enum {string}
         */
        JobStage: "queued" | "analyzing_video" | "extracting_audio" | "transcribing" | "awaiting_subtitle_review" | "generating_note" | "generating_frames" | "preparing_review" | "awaiting_note_review" | "finalizing" | "completed" | "failed" | "cancelling" | "cancelled";
        /**
         * JobStatus
         * @enum {string}
         */
        JobStatus: "pending" | "running" | "cancelling" | "awaiting_subtitle_confirmation" | "awaiting_note_review" | "succeeded" | "failed" | "cancelled";
        /** JobSummary */
        JobSummary: {
            /** Active Version Id */
            active_version_id?: string | null;
            /**
             * Artifact Count
             * @default 0
             */
            artifact_count: number;
            /** Created At */
            created_at?: string | null;
            /** Duration Seconds */
            duration_seconds?: number | null;
            /** Error */
            error?: string | null;
            failure_context?: components["schemas"]["FailureContext"] | null;
            /** Job Id */
            job_id: string;
            /**
             * Note Version Count
             * @default 0
             */
            note_version_count: number;
            /** Original Filename */
            original_filename: string;
            status: components["schemas"]["JobStatus"];
            /** Title */
            title: string;
            /** Updated At */
            updated_at?: string | null;
        };
        /** LocalModelsRuntimeStatus */
        LocalModelsRuntimeStatus: {
            /** Hint */
            hint: string;
            /** Models */
            models?: string[];
            /** Root */
            root: string;
            /**
             * Root Source
             * @enum {string}
             */
            root_source: "environment" | "settings" | "default" | "missing";
        };
        /** LocalTranscriptionDependencyInstallState */
        LocalTranscriptionDependencyInstallState: {
            /**
             * Error
             * @default
             */
            error: string;
            /**
             * Progress
             * @default 0
             */
            progress: number;
            /**
             * Python Path
             * @default
             */
            python_path: string;
            /**
             * Status
             * @default idle
             * @enum {string}
             */
            status: "idle" | "pending" | "running" | "succeeded" | "failed";
        };
        /**
         * LocalWhisperComputeType
         * @enum {string}
         */
        LocalWhisperComputeType: "default" | "int8" | "int8_float16" | "float16" | "float32";
        /**
         * LocalWhisperDevice
         * @enum {string}
         */
        LocalWhisperDevice: "auto" | "cpu" | "cuda";
        /** ModelDownloadRequest */
        ModelDownloadRequest: {
            /**
             * Model Name
             * @default small
             */
            model_name: string;
        };
        /** ModelDownloadState */
        ModelDownloadState: {
            /**
             * Error
             * @default
             */
            error: string;
            /** Model Name */
            model_name: string;
            /** Model Root */
            model_root: string;
            /**
             * Progress
             * @default 0
             */
            progress: number;
            /**
             * Status
             * @default pending
             * @enum {string}
             */
            status: "idle" | "pending" | "running" | "succeeded" | "failed";
        };
        /** NoteChunkIndex */
        NoteChunkIndex: {
            /** Chunks */
            chunks?: components["schemas"]["NoteChunkMeta"][];
            /**
             * Total Segments
             * @default 0
             */
            total_segments: number;
        };
        /** NoteChunkMeta */
        NoteChunkMeta: {
            /** End Time */
            end_time: number;
            /** Id */
            id: string;
            /** Index */
            index: number;
            /** Label */
            label: string;
            /** Segment End */
            segment_end: number;
            /** Segment Start */
            segment_start: number;
            /** Start Time */
            start_time: number;
            /**
             * Status
             * @default succeeded
             */
            status: string;
            /**
             * Title
             * @default
             */
            title: string;
            /** Total */
            total: number;
        };
        /**
         * NoteLanguage
         * @enum {string}
         */
        NoteLanguage: "zh" | "en" | "follow";
        /**
         * NoteStyle
         * @enum {string}
         */
        NoteStyle: "minimal" | "detailed" | "tutorial" | "academic" | "task_oriented" | "meeting_minutes";
        /** NoteVersion */
        NoteVersion: {
            /**
             * Active
             * @default false
             */
            active: boolean;
            /** Created At */
            created_at?: string;
            /** Draft Path */
            draft_path?: string | null;
            /** Evidence Path */
            evidence_path?: string | null;
            /**
             * Extras Length
             * @default 0
             */
            extras_length: number;
            /**
             * Extras Present
             * @default false
             */
            extras_present: boolean;
            /** Frame Dir */
            frame_dir: string;
            /** Frame Limit */
            frame_limit: number;
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** @default openai_chat_completions */
            note_api_protocol: components["schemas"]["AIProtocol"];
            /** Note Base Url */
            note_base_url: string;
            /**
             * Note Context Window Tokens
             * @default 32768
             */
            note_context_window_tokens: number;
            /** Note Language */
            note_language: string;
            /**
             * Note Max Output Tokens
             * @default 8192
             */
            note_max_output_tokens: number;
            /** Note Model */
            note_model: string;
            /** Note Path */
            note_path: string;
            note_style: components["schemas"]["NoteStyle"];
            /**
             * Note Thinking Enabled
             * @default false
             */
            note_thinking_enabled: boolean;
            /**
             * Selected
             * @default true
             */
            selected: boolean;
        };
        /** NoteVersionIndex */
        NoteVersionIndex: {
            /** Active Version Id */
            active_version_id?: string | null;
            /** Selected Version Ids */
            selected_version_ids?: string[];
            /** Versions */
            versions?: components["schemas"]["NoteVersion"][];
        };
        /** NoteVersionSelection */
        NoteVersionSelection: {
            /** Active Version Id */
            active_version_id?: string | null;
            /** Selected Version Ids */
            selected_version_ids?: string[];
        };
        /**
         * PerformanceMode
         * @enum {string}
         */
        PerformanceMode: "fast" | "balanced" | "accurate";
        /** QualityIssue */
        QualityIssue: {
            /** Chapter Index */
            chapter_index?: number | null;
            /** Frame Ids */
            frame_ids?: string[];
            /** Message */
            message: string;
            /**
             * Severity
             * @enum {string}
             */
            severity: "info" | "warning" | "error";
            /** Type */
            type: string;
        };
        /** QualityReport */
        QualityReport: {
            /** Chapter Reports */
            chapter_reports?: components["schemas"]["ChapterQualityReport"][];
            /** Issues */
            issues?: components["schemas"]["QualityIssue"][];
            scores: components["schemas"]["QualityScores"];
            /**
             * Status
             * @enum {string}
             */
            status: "ready" | "review_recommended" | "needs_attention";
        };
        /** QualityScores */
        QualityScores: {
            /** Coverage */
            coverage: number;
            /**
             * Evidence
             * @default 1
             */
            evidence: number;
            /** Frames */
            frames: number;
            /** Stability */
            stability: number;
            /** Structure */
            structure: number;
        };
        /** ReviewAssets */
        ReviewAssets: {
            frame_candidates: components["schemas"]["FrameCandidateIndex"];
            quality_report: components["schemas"]["QualityReport"];
            review_draft: components["schemas"]["ReviewDraft"];
        };
        /** ReviewDraft */
        ReviewDraft: {
            /**
             * Finalized Note Sha256
             * @default
             */
            finalized_note_sha256: string;
            /** Note Version Id */
            note_version_id?: string | null;
            /** Paragraphs */
            paragraphs?: components["schemas"]["ReviewDraftParagraph"][];
            /**
             * Schema Version
             * @default 1
             */
            schema_version: number;
            /**
             * Source Note Sha256
             * @default
             */
            source_note_sha256: string;
            /**
             * Source Transcript Sha256
             * @default
             */
            source_transcript_sha256: string;
            /**
             * Title
             * @default
             */
            title: string;
        };
        /** ReviewDraftParagraph */
        ReviewDraftParagraph: {
            /**
             * Body
             * @default
             */
            body: string;
            /** Chapter Index */
            chapter_index: number;
            /** End Time */
            end_time: number;
            /**
             * Evidence Reference Valid
             * @default false
             */
            evidence_reference_valid: boolean;
            /** Evidence Segment Ids */
            evidence_segment_ids?: string[];
            /** Id */
            id: string;
            /** Selected Frame Ids */
            selected_frame_ids?: string[];
            /** Start Time */
            start_time: number;
            /**
             * Status
             * @default needs_review
             * @enum {string}
             */
            status: "needs_review" | "edited" | "approved";
            /** Subtitle Segments */
            subtitle_segments?: components["schemas"]["ReviewSubtitleSegment"][];
            /** Title */
            title: string;
            /** Unsupported Numeric Claims */
            unsupported_numeric_claims?: string[];
            /** Unsupported Technical Identifiers */
            unsupported_technical_identifiers?: string[];
        };
        /** ReviewDraftParagraphUpdate */
        ReviewDraftParagraphUpdate: {
            /** Body */
            body: string;
            /** Selected Frame Ids */
            selected_frame_ids?: string[];
            /**
             * Status
             * @default edited
             * @enum {string}
             */
            status: "needs_review" | "edited" | "approved";
        };
        /** ReviewSubtitleSegment */
        ReviewSubtitleSegment: {
            /** End */
            end: number;
            /**
             * Segment Id
             * @default
             */
            segment_id: string;
            /** Start */
            start: number;
            /** Text */
            text: string;
        };
        /** RuntimeCapabilities */
        RuntimeCapabilities: {
            audio_transcriptions: components["schemas"]["RuntimeCapability"];
            chat_audio: components["schemas"]["RuntimeCapability"];
            local_transcription_cpu: components["schemas"]["RuntimeCapability"];
            local_transcription_cuda: components["schemas"]["RuntimeCapability"];
            note_generation: components["schemas"]["RuntimeCapability"];
            uploaded_subtitle: components["schemas"]["RuntimeCapability"];
            video_processing: components["schemas"]["RuntimeCapability"];
        };
        /** RuntimeCapability */
        RuntimeCapability: {
            /** Available */
            available: boolean;
            /** Reason */
            reason: string;
            /**
             * Requires Credentials
             * @default false
             */
            requires_credentials: boolean;
        };
        /** RuntimeState */
        RuntimeState: {
            capabilities: components["schemas"]["RuntimeCapabilities"];
            faster_whisper: components["schemas"]["FasterWhisperRuntimeStatus"];
            ffmpeg: components["schemas"]["FFmpegRuntimeStatus"];
            local_models: components["schemas"]["LocalModelsRuntimeStatus"];
            /** Ok */
            ok: boolean;
            settings: components["schemas"]["SettingsStorageStatus"];
        };
        /** SettingsStorageStatus */
        SettingsStorageStatus: {
            /**
             * Error
             * @default
             */
            error: string;
            /** Path */
            path: string;
            /** Schema Version */
            schema_version: number;
            /** Secret Provider */
            secret_provider: string;
            /** Secrets Encrypted */
            secrets_encrypted: boolean;
            /** Warning */
            warning: string;
        };
        /** TranscriptCorrectionApplyRequest */
        TranscriptCorrectionApplyRequest: {
            /**
             * Extras
             * @default
             */
            extras: string;
            /**
             * Frame Limit
             * @default 6
             */
            frame_limit: number;
            /** Note Api Key */
            note_api_key: string;
            /** @default openai_chat_completions */
            note_api_protocol: components["schemas"]["AIProtocol"];
            /**
             * Note Base Url
             * @default https://api.openai.com/v1
             */
            note_base_url: string;
            /**
             * Note Context Window Tokens
             * @default 32768
             */
            note_context_window_tokens: number;
            note_language: components["schemas"]["NoteLanguage"];
            /**
             * Note Max Output Tokens
             * @default 8192
             */
            note_max_output_tokens: number;
            /**
             * Note Model
             * @default gpt-5.5
             */
            note_model: string;
            /** @default detailed */
            note_style: components["schemas"]["NoteStyle"];
            /**
             * Note Thinking Enabled
             * @default false
             */
            note_thinking_enabled: boolean;
        };
        /** TranscriptCorrectionPreview */
        TranscriptCorrectionPreview: {
            /** Changed Count */
            changed_count: number;
            /**
             * Job Id
             * @default
             */
            job_id: string;
            /** Segments */
            segments?: components["schemas"]["TranscriptCorrectionSegment"][];
        };
        /** TranscriptCorrectionRequest */
        TranscriptCorrectionRequest: {
            /**
             * Instructions
             * @default
             */
            instructions: string;
            /** Note Api Key */
            note_api_key: string;
            /** @default openai_chat_completions */
            note_api_protocol: components["schemas"]["AIProtocol"];
            /**
             * Note Base Url
             * @default https://api.openai.com/v1
             */
            note_base_url: string;
            /**
             * Note Context Window Tokens
             * @default 32768
             */
            note_context_window_tokens: number;
            /**
             * Note Max Output Tokens
             * @default 8192
             */
            note_max_output_tokens: number;
            /**
             * Note Model
             * @default gpt-5.5
             */
            note_model: string;
            /**
             * Note Thinking Enabled
             * @default false
             */
            note_thinking_enabled: boolean;
        };
        /** TranscriptCorrectionSegment */
        TranscriptCorrectionSegment: {
            /**
             * Changed
             * @default false
             */
            changed: boolean;
            /** Corrected Text */
            corrected_text: string;
            /** End */
            end: number;
            /** Index */
            index: number;
            /** Original Text */
            original_text: string;
            /** Start */
            start: number;
        };
        /**
         * TranscriptionLanguage
         * @enum {string}
         */
        TranscriptionLanguage: "auto" | "zh" | "en";
        /**
         * TranscriptionMode
         * @enum {string}
         */
        TranscriptionMode: "audio_transcriptions" | "chat_audio" | "local_faster_whisper";
        /** TranscriptionWorkProgress */
        TranscriptionWorkProgress: {
            /**
             * Cache Hits
             * @default 0
             */
            cache_hits: number;
            /**
             * Completed Chunks
             * @default 0
             */
            completed_chunks: number;
            /**
             * Completed Seconds
             * @default 0
             */
            completed_seconds: number;
            /**
             * Compute Type
             * @default
             */
            compute_type: string;
            /** Current Chunk */
            current_chunk?: number | null;
            /**
             * Device
             * @default
             */
            device: string;
            /** Eta Seconds */
            eta_seconds?: number | null;
            /** Realtime Factor */
            realtime_factor?: number | null;
            /**
             * Resumable
             * @default false
             */
            resumable: boolean;
            /**
             * Total Chunks
             * @default 0
             */
            total_chunks: number;
            /**
             * Total Seconds
             * @default 0
             */
            total_seconds: number;
        };
        /** UserSettings */
        UserSettings: {
            /**
             * External Python Path
             * @default
             */
            external_python_path: string;
            /**
             * Extras
             * @default
             */
            extras: string;
            /**
             * Faster Whisper Model Dir
             * @default
             */
            faster_whisper_model_dir: string;
            /**
             * Frame Limit
             * @default 6
             */
            frame_limit: number;
            /** @default default */
            local_whisper_compute_type: components["schemas"]["LocalWhisperComputeType"];
            /** @default auto */
            local_whisper_device: components["schemas"]["LocalWhisperDevice"];
            /**
             * Note Api Key
             * @default
             */
            note_api_key: string;
            /** @default openai_chat_completions */
            note_api_protocol: components["schemas"]["AIProtocol"];
            /**
             * Note Base Url
             * @default https://api.openai.com/v1
             */
            note_base_url: string;
            /**
             * Note Context Window Tokens
             * @default 32768
             */
            note_context_window_tokens: number;
            /** @default zh */
            note_language: components["schemas"]["NoteLanguage"];
            /**
             * Note Max Output Tokens
             * @default 8192
             */
            note_max_output_tokens: number;
            /**
             * Note Model
             * @default gpt-5.5
             */
            note_model: string;
            /** @default detailed */
            note_style: components["schemas"]["NoteStyle"];
            /**
             * Note Thinking Enabled
             * @default false
             */
            note_thinking_enabled: boolean;
            /** @default balanced */
            performance_mode: components["schemas"]["PerformanceMode"];
            /**
             * Python Package Install Mode
             * @default default
             * @enum {string}
             */
            python_package_install_mode: "default" | "user";
            /**
             * Transcription Api Key
             * @default
             */
            transcription_api_key: string;
            /**
             * Transcription Base Url
             * @default https://api.openai.com/v1
             */
            transcription_base_url: string;
            /** @default auto */
            transcription_language: components["schemas"]["TranscriptionLanguage"];
            /** @default local_faster_whisper */
            transcription_mode: components["schemas"]["TranscriptionMode"];
            /**
             * Transcription Model
             * @default small
             */
            transcription_model: string;
        };
        /** UserSettingsUpdate */
        UserSettingsUpdate: {
            /** External Python Path */
            external_python_path?: string | null;
            /** Extras */
            extras?: string | null;
            /** Faster Whisper Model Dir */
            faster_whisper_model_dir?: string | null;
            /** Frame Limit */
            frame_limit?: number | null;
            local_whisper_compute_type?: components["schemas"]["LocalWhisperComputeType"] | null;
            local_whisper_device?: components["schemas"]["LocalWhisperDevice"] | null;
            /** Note Api Key */
            note_api_key?: string | null;
            note_api_protocol?: components["schemas"]["AIProtocol"] | null;
            /** Note Base Url */
            note_base_url?: string | null;
            /** Note Context Window Tokens */
            note_context_window_tokens?: number | null;
            note_language?: components["schemas"]["NoteLanguage"] | null;
            /** Note Max Output Tokens */
            note_max_output_tokens?: number | null;
            /** Note Model */
            note_model?: string | null;
            note_style?: components["schemas"]["NoteStyle"] | null;
            /** Note Thinking Enabled */
            note_thinking_enabled?: boolean | null;
            performance_mode?: components["schemas"]["PerformanceMode"] | null;
            /** Python Package Install Mode */
            python_package_install_mode?: ("default" | "user") | null;
            /** Transcription Api Key */
            transcription_api_key?: string | null;
            /** Transcription Base Url */
            transcription_base_url?: string | null;
            transcription_language?: components["schemas"]["TranscriptionLanguage"] | null;
            transcription_mode?: components["schemas"]["TranscriptionMode"] | null;
            /** Transcription Model */
            transcription_model?: string | null;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    list_ai_models_api_ai_models_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AIModelListRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AIModelListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    test_ai_connection_api_ai_test_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AIConnectionTestRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AIConnectionTestResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthState"];
                };
            };
        };
    };
    list_jobs_api_jobs_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobHistory"];
                };
            };
        };
    };
    create_job_api_jobs_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_create_job_api_jobs_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    suggest_frame_count_api_jobs_frame_suggestion_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_suggest_frame_count_api_jobs_frame_suggestion_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FrameSuggestion"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_job_api_jobs__job_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobPublicState"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_job_api_jobs__job_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_job_activity_api_jobs__job_id__activity_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobActivitySnapshot"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_asset_api_jobs__job_id__assets__asset_path__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
                asset_path: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_job_api_jobs__job_id__cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobPublicState"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_diagnostics_zip_api_jobs__job_id__diagnostics_zip_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_zip_api_jobs__job_id__download_zip_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    finalize_job_api_jobs__job_id__finalize_post: {
        parameters: {
            query?: {
                version_id?: string | null;
                expected_state_revision?: number | null;
                expected_artifact_revision?: string | null;
            };
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobPublicState"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_frame_candidates_api_jobs__job_id__frame_candidates_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FrameCandidateIndex"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reject_job_frame_candidate_api_jobs__job_id__frame_candidates__candidate_id__reject_post: {
        parameters: {
            query?: {
                expected_state_revision?: number | null;
                expected_artifact_revision?: string | null;
            };
            header?: never;
            path: {
                job_id: string;
                candidate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FrameCandidateIndex"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    select_job_frame_candidate_api_jobs__job_id__frame_candidates__candidate_id__select_post: {
        parameters: {
            query?: {
                expected_state_revision?: number | null;
                expected_artifact_revision?: string | null;
            };
            header?: never;
            path: {
                job_id: string;
                candidate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FrameCandidateIndex"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_note_chunks_api_jobs__job_id__note_chunks_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NoteChunkIndex"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    regenerate_note_chunk_api_jobs__job_id__note_chunks__chunk_id__regenerate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
                chunk_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/x-www-form-urlencoded": components["schemas"]["Body_regenerate_note_chunk_api_jobs__job_id__note_chunks__chunk_id__regenerate_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_note_versions_api_jobs__job_id__note_versions_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NoteVersionIndex"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    regenerate_note_version_endpoint_api_jobs__job_id__note_versions_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/x-www-form-urlencoded": components["schemas"]["Body_regenerate_note_version_endpoint_api_jobs__job_id__note_versions_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_note_version_selection_api_jobs__job_id__note_versions_patch: {
        parameters: {
            query?: {
                expected_state_revision?: number | null;
                expected_artifact_revision?: string | null;
            };
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NoteVersionSelection"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NoteVersionIndex"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    preview_note_api_jobs__job_id__preview_note_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/plain": string;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    preview_note_version_api_jobs__job_id__preview_note__version_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
                version_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/plain": string;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    preview_subtitles_api_jobs__job_id__preview_subtitles_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/plain": string;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_quality_report_api_jobs__job_id__quality_report_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QualityReport"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    prepare_job_review_assets_api_jobs__job_id__review_assets_prepare_post: {
        parameters: {
            query?: {
                version_id?: string | null;
            };
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewAssets"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_job_review_draft_api_jobs__job_id__review_draft_get: {
        parameters: {
            query?: {
                version_id?: string | null;
            };
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewDraft"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_job_review_draft_paragraph_api_jobs__job_id__review_draft_paragraphs__paragraph_id__patch: {
        parameters: {
            query?: {
                version_id?: string | null;
                expected_state_revision?: number | null;
                expected_artifact_revision?: string | null;
            };
            header?: never;
            path: {
                job_id: string;
                paragraph_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReviewDraftParagraphUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewDraft"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_job_storage_api_jobs__job_id__storage_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    confirm_subtitles_api_jobs__job_id__subtitles_confirm_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/x-www-form-urlencoded": components["schemas"]["Body_confirm_subtitles_api_jobs__job_id__subtitles_confirm_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    regenerate_subtitles_api_jobs__job_id__subtitles_regenerate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/x-www-form-urlencoded": components["schemas"]["Body_regenerate_subtitles_api_jobs__job_id__subtitles_regenerate_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_transcript_correction_endpoint_api_jobs__job_id__transcript_corrections_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TranscriptCorrectionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TranscriptCorrectionPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    apply_transcript_correction_endpoint_api_jobs__job_id__transcript_corrections_apply_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TranscriptCorrectionApplyRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_transcription_cache_api_jobs__job_id__transcription_cache_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    resume_transcription_api_jobs__job_id__transcription_resume_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_faster_whisper_model_endpoint_api_models_faster_whisper_download_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ModelDownloadRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ModelDownloadState"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_faster_whisper_model_download_api_models_faster_whisper_download__model_name__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                model_name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ModelDownloadState"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    ready_api_ready_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    runtime_api_runtime_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RuntimeState"];
                };
            };
        };
    };
    get_cuda_dependency_install_api_runtime_cuda_dependencies_install_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CudaDependencyInstallState"];
                };
            };
        };
    };
    install_cuda_dependencies_api_runtime_cuda_dependencies_install_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CudaDependencyInstallState"];
                };
            };
        };
    };
    clear_faster_whisper_cache_api_runtime_faster_whisper_cache_clear_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    get_local_dependency_install_api_runtime_local_dependencies_install_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalTranscriptionDependencyInstallState"];
                };
            };
        };
    };
    install_local_dependencies_api_runtime_local_dependencies_install_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocalTranscriptionDependencyInstallState"];
                };
            };
        };
    };
    get_settings_api_settings_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserSettings"];
                };
            };
        };
    };
    delete_settings_api_settings_delete: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserSettings"];
                };
            };
        };
    };
    update_settings_api_settings_patch: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UserSettingsUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserSettings"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
