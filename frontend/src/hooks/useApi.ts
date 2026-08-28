import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";
import { ApiError } from "../api/client";

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  status: number | null;
}

/**
 * Small shared data-fetching primitive - not React Query. This codebase's
 * existing pattern (useComplaintFeed) was already a hand-rolled hook; this
 * generalizes it to any async loader instead of pulling in a large new
 * dependency for what amounts to "fetch, remember the last result, expose
 * a refetch". `deps` re-runs the loader exactly like a useEffect dep array.
 */
export function useApi<T>(loader: () => Promise<T>, deps: DependencyList): AsyncState<T> & { reload: () => void } {
  const [state, setState] = useState<AsyncState<T>>({ data: null, loading: true, error: null, status: null });
  const generation = useRef(0);

  const run = useCallback(() => {
    const gen = ++generation.current;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    loader()
      .then((data) => {
        if (gen === generation.current) setState({ data, loading: false, error: null, status: 200 });
      })
      .catch((err) => {
        if (gen !== generation.current) return;
        if (err instanceof ApiError) {
          setState({ data: null, loading: false, error: err.message, status: err.status });
        } else {
          setState({ data: null, loading: false, error: "Could not reach TRACE-X.", status: null });
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run]);

  return { ...state, reload: run };
}
