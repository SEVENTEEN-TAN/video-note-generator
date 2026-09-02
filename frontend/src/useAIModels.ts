import { useCallback, useEffect, useRef, useState } from "react";

import { fetchAIModels } from "./api";
import type { AIModelInfo, AIProtocol } from "./types";

type UseAIModelsOptions = {
  apiKey: string;
  baseUrl: string;
  protocol: AIProtocol;
};

export function useAIModels({ apiKey, baseUrl, protocol }: UseAIModelsOptions) {
  const [models, setModels] = useState<AIModelInfo[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const requestEpochRef = useRef(0);
  const requestControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    requestEpochRef.current += 1;
    requestControllerRef.current?.abort();
    requestControllerRef.current = null;
    setModels([]);
    setError("");
    setIsLoading(false);
  }, [apiKey, baseUrl, protocol]);

  useEffect(
    () => () => {
      requestEpochRef.current += 1;
      requestControllerRef.current?.abort();
    },
    []
  );

  const refreshModels = useCallback(async () => {
    setError("");
    if (!apiKey.trim() || !baseUrl.trim()) {
      setError("请先填写 Base URL 和 API Key。");
      return;
    }
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    const requestEpoch = requestEpochRef.current + 1;
    requestEpochRef.current = requestEpoch;
    setIsLoading(true);
    try {
      const response = await fetchAIModels({ api_key: apiKey, base_url: baseUrl, protocol }, controller.signal);
      if (requestEpoch !== requestEpochRef.current) {
        return;
      }
      setModels(response.models ?? []);
      if (!response.models?.length) {
        setError("服务器没有返回可用模型，可继续手动填写模型名称。");
      }
    } catch (requestError) {
      if (requestEpoch !== requestEpochRef.current || controller.signal.aborted) {
        return;
      }
      setModels([]);
      setError(requestError instanceof Error ? requestError.message : "服务器模型列表获取失败。");
    } finally {
      if (requestEpoch === requestEpochRef.current) {
        setIsLoading(false);
      }
    }
  }, [apiKey, baseUrl, protocol]);

  return { error, isLoading, models, refreshModels };
}
