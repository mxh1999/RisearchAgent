# CitationProvider: Semantic Scholar 集成与降级

> Explorer 对外部引用数据的依赖抽象。v1 实现 Semantic Scholar，预留 OpenAlex 替代。
> 任何 citation 调用必须能降级运行。

## 接口抽象

```python
class CitationProvider(ABC):
    @abstractmethod
    async def get_paper(self, arxiv_id: str) -> Optional[PaperCitationInfo]:
        """拿论文的元数据 + citation_count + reference_count"""
        ...

    @abstractmethod
    async def get_references(self, arxiv_id: str, limit: int = 20) -> List[RelatedPaper]:
        """这篇引用了哪些"""
        ...

    @abstractmethod
    async def get_citations(self, arxiv_id: str, limit: int = 20) -> List[RelatedPaper]:
        """哪些引用了这篇"""
        ...

    @abstractmethod
    async def get_related(self, arxiv_id: str, limit: int = 10) -> List[RelatedPaper]:
        """相似/推荐"""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """本次 run 内是否已降级"""
        ...


@dataclass
class PaperCitationInfo:
    arxiv_id: str
    citation_count: int
    reference_count: int
    fetched_at: datetime


@dataclass
class RelatedPaper:
    arxiv_id: Optional[str]          # 可能有 SS ID 但无 arxiv_id
    title: str
    ss_paper_id: Optional[str]
    year: Optional[int]
    citation_count: Optional[int]
```

## 实现：SemanticScholarProvider

```python
class SemanticScholarProvider(CitationProvider):
    BASE_URL = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self._cache: Dict[str, Any] = {}             # run 内 memoize
        self._consecutive_errors = 0
        self._degraded = False

        # 速率限制（无 key 1 req/s，有 key 100 req/s）
        self._rate_limiter = AsyncRateLimiter(
            rate=100 if api_key else 1,
            period=1.0,
        )

    async def get_paper(self, arxiv_id: str) -> Optional[PaperCitationInfo]:
        if self._degraded:
            return None
        cache_key = f"paper:{arxiv_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            async with self._rate_limiter:
                result = await self._request(f"/paper/arXiv:{arxiv_id}",
                                             params={"fields": "citationCount,referenceCount"})
            info = PaperCitationInfo(
                arxiv_id=arxiv_id,
                citation_count=result.get("citationCount", 0),
                reference_count=result.get("referenceCount", 0),
                fetched_at=datetime.now(),
            )
            self._cache[cache_key] = info
            self._consecutive_errors = 0
            return info
        except Exception as e:
            return self._handle_error(e)
```

其他方法类似模式：缓存 → 限速 → 请求 → 错误处理。

## 降级策略

```python
DEGRADE_THRESHOLD = 3    # 连续 3 次错误后降级

def _handle_error(self, e: Exception):
    self._consecutive_errors += 1
    logger.warning(f"Semantic Scholar error: {e}")
    if self._consecutive_errors >= DEGRADE_THRESHOLD:
        self._degraded = True
        logger.error("Semantic Scholar degraded for rest of run")
    return None
```

一旦 `_degraded=True`：
- 本 run 所有后续调用立刻返回 None（不再试）
- state.metadata 加 flag `citation_provider_degraded=True`
- Dashboard 显示 `⚠ Citation provider unavailable — degrading to metadata-only`
- Field map 合成时在 `notes` 中注明

**不降级回升**：即便 API 恢复，本 run 也不重试——避免行为不一致。下次 run 新建 provider。

## NullProvider（用户主动关闭时）

```python
class NullProvider(CitationProvider):
    """全部返回空值。用户配置 citation_provider: none 时用。"""
    async def get_paper(self, arxiv_id): return None
    async def get_references(self, arxiv_id, limit=20): return []
    async def get_citations(self, arxiv_id, limit=20): return []
    async def get_related(self, arxiv_id, limit=10): return []
    def is_available(self): return False
```

## 配置

```yaml
# config.yaml
explore:
  citation_provider: semantic_scholar     # or openalex / none
  semantic_scholar_api_key: ${SEMANTIC_SCHOLAR_KEY}  # optional
```

读取逻辑：
```python
def make_citation_provider(config) -> CitationProvider:
    kind = config.get("citation_provider", "semantic_scholar")
    if kind == "none":
        return NullProvider()
    elif kind == "semantic_scholar":
        return SemanticScholarProvider(api_key=config.get("semantic_scholar_api_key"))
    elif kind == "openalex":
        return OpenAlexProvider()           # v2
    else:
        raise ValueError(f"Unknown citation_provider: {kind}")
```

## 对 Executor 的影响

Executor 调用 Provider 的地方：

| Action | 使用方法 |
|---|---|
| `search` / `search_by_author` | 新论文进池后异步 `get_paper()` 批量拉 citation_count |
| `fetch_citations` | `get_references()` 或 `get_citations()` |
| `fetch_related` | `get_related()` |

**Provider 降级不影响 action 成功**：
- `search` 仍能加新论文，只是 citation_count=None
- `fetch_citations` / `fetch_related` 在降级时直接报 "provider unavailable, action skipped"，Spec 记录后 Planner 换别的动作

## 对 Spec 规则的影响

v1 的 11 条规则**没有一条强依赖 citation 数据**（classic baseline 用 year_range 判）。降级不影响 Spec 运行。

Field map 里 "Classic baselines" section 依赖 citation_count——降级时这部分可能稀疏，通过 `notes` 提示。

## 速率限制实现

```python
class AsyncRateLimiter:
    def __init__(self, rate: float, period: float = 1.0):
        self.rate = rate
        self.period = period
        self._tokens = rate
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.rate, self._tokens + elapsed * self.rate / self.period)
            self._last_refill = now
            if self._tokens < 1:
                wait = (1 - self._tokens) * self.period / self.rate
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1
```

Token bucket 算法，标准做法。

## 测试

- **NullProvider** 的所有方法返回空
- **SemanticScholarProvider 降级**：mock 3 次 error → `is_available() == False`，后续调用返回 None
- **缓存命中**：同一 arxiv_id 调两次，API 只请求一次
- **速率限制**：构造 rate=2，发 5 个并发请求，完成时间 ≥ 2s
- **错误不 propagate**：API 抛 HTTPError，provider 方法返回 None 而非抛错

实网测试用极少量调用（2–3 次），标 `@pytest.mark.network`，不默认跑。

## 开放点

- **批量接口**：Semantic Scholar 有 `POST /graph/v1/paper/batch`，一次拉 500 个。若 skim_abstract 后需要批量 citation，用这个省 RPS。v1 先不用
- **Arxiv ID 格式差异**：SS 接受 `arXiv:2401.12345`；Explorer state 里只存 `2401.12345`，provider 内部做格式转换
- **缓存跨 run 复用**：v1 仅 run 内缓存；v2 可加 SQLite 持久化缓存（citation 数据时效长，跨 run 复用省 API 额度）
