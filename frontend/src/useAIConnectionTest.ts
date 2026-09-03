import { useCallback, useEffect, useRef, useState } from "react";

import { testAIConnection } from "./api";
import type { AIProtocol } from "./types";

type UseAIConnectionTestOptions = {
  apiKey: string;
  baseUrl: string;
  maxOutputTokens: number;
  model: string;
  protocol: AIProtocol;
  thinkingEnabled: boolean;
};

export function useAIConnectionTest({
  apiKey,
  baseUrl,
  maxOutputTokens,
  model,
  protocol,
  thinkingEnabled
}: UseAIConnectionTestOptions) {
  const [isTesting, setIsTesting] = useState(false);
  const [message, setMessage] = useState("");
  const [succeeded, setSucceeded] = useState(false);
  const requestEpochRef = useRef(0);
  const requestControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    requestEpochRef.current += 1;
    requestControllerRef.current?.abort();
    requestControllerRef.current = null;
    setIsTesting(false);
    setMessage("");
    setSucceeded(false);
  }, [apiKey, baseUrl, maxOutputTokens, model, protocol, thinkingEnabled]);

  useEffect(
    () => () => {
      requestEpochRef.current += 1;
      requestControllerRef.current?.abort();
    },
    []
  );

  const runTest = useCallback(async () => {
    setMessage("");
    setSucceeded(false);
    if (!apiKey.trim() || !baseUrl.trim() || !model.trim()) {
      setMessage("请先填写 Base URL、模型和 API Key。");
      return;
    }
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    const requestEpoch = requestEpochRef.current + 1;
    requestEpochRef.current = requestEpoch;
    setIsTesting(true);
    try {
      const result = await testAIConnection(
        {
          api_key: apiKey,
          base_url: baseUrl,
          model,
          protocol,
          thinking_enabled: thinkingEnabled,
          max_output_tokens: maxOutputTokens
        },
        controller.signal
      );
      if (requestEpoch !== requestEpochRef.current) {
        return;
      }
      setSucceeded(result.ok && result.response_length > 0);
      setMessage(
        result.json_valid
          ? "接口测试通过 · " + result.elapsed_ms + " ms · JSON 响应正常"
          : "接口已响应 · " + result.elapsed_ms + " ms · 返回内容不是 JSON"
      );
    } catch (error) {
      if (requestEpoch !== requestEpochRef.current || controller.signal.aborted) {
        return;
      }
      setMessage(error instanceof Error ? error.message : "AI 接口测试失败。");
    } finally {
      if (requestEpoch === requestEpochRef.current) {
        setIsTesting(false);
      }
    }
  }, [apiKey, baseUrl, maxOutputTokens, model, protocol, thinkingEnabled]);

  return { isTesting, message, runTest, succeeded };
}
