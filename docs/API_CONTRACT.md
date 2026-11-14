# Implementation contract

All endpoints `/api/v1`. Dataset responses include `dataset_id`, `filename`, `active_version`, `revision`. Upload returns a private `token`; subsequent dataset requests use `X-Session-Token`. Never tokens in URLs. JSON errors `{ "error": {"code": "...", "message": "..."} }`.

- GET `/health` -> `{status, app_env}`
- GET `/samples` -> `{samples:[{id,name,description}]}`
- POST `/datasets/upload` multipart `file` -> `{dataset_id,token,filename,inspection:{format,sheets,encoding,delimiter,has_header,preview}}`
- POST `/datasets/sample/{sample_id}` -> same upload response
- POST `/datasets/{id}/ingest` `{sheet:null,header:0,delimiter:null,encoding:null}` (`header:null` means no header) -> 202 `{job_id}`
- GET `/datasets/{id}/jobs/{job_id}` -> `{job_id,status:queued|running|succeeded|failed|timed_out,error:null,result:null|object}`
- GET `/datasets/{id}` -> dataset metadata
- GET `/datasets/{id}/preview?offset=0&limit=50` -> `{columns:[string],rows:[{row_id:int,values:[scalar]}],total,version}`
- GET `/datasets/{id}/profile` -> profile below
- GET `/datasets/{id}/columns/{column}` -> column profile
- GET `/datasets/{id}/quality` -> `{issues:[issue]}`
- POST `/datasets/{id}/quality` `{domain_rules:{column:{min:0,max:100}}}` -> `{issues:[issue]}` including explicit range findings. Finite numeric bounds, either or both, minimum <= maximum; unknown columns rejected. Read-only, does not alter versions or cached default findings.
- GET `/datasets/{id}/recommendations` -> `{recommendations:[recommendation]}`
- POST `/datasets/{id}/anomalies` `{method:iqr|mad|isolation_forest,columns:[string],threshold:3.5}` -> `{method,findings:[{column,row_ids,values,count,thresholds,explanation}],warnings:[]}`. IQR default threshold 1.5; MAD 3.5; isolation threshold ignored.
- POST `/datasets/{id}/cleaning/preview` `{operation:{kind,column:null,params:{}},expected_version:0,expected_revision:0}` -> `{preview_id,version,operation,affected_cells,affected_rows,rows_removed,rows_added,changes:[{row_id,column,before,after}],metrics_before,metrics_after}`
- POST `/datasets/{id}/cleaning/apply` `{preview_id,expected_version:0,expected_revision:0,approved:true}` -> metadata. Approval must be a strict JSON boolean. Apply accepts only the exact server-held reviewed operation; stale revisions or previews at/after their expiration return 409.
- POST `/datasets/{id}/undo`, `/redo`, `/reset` `{expected_version,expected_revision}` -> metadata
- POST `/datasets/{id}/restore` `{version,expected_version,expected_revision}` -> metadata
- GET `/datasets/{id}/history` -> `{active_version,revision,versions:[{version,parent,operation,created_at}]}`
- GET `/datasets/{id}/export?format=csv|xlsx` -> safe attachment (use authorized fetch + Blob)
- GET `/datasets/{id}/report?format=json|html` -> safe attachment; HTML can be printed as PDF in browser
- GET `/datasets/{id}/code?language=python|sql` -> text attachment (PostgreSQL reference SQL)
- GET `/ai/status` -> `{enabled,available,model,reason}`
- POST `/datasets/{id}/ai/explain` `{}` -> `{source,explanation,warnings,reason}`. Aggregate-only, no raw samples/column names.
- DELETE `/datasets/{id}` -> `{deleted:true}`

All six attachments require ingestion and name the sanitized source stem plus the actual exported active version in `Content-Disposition`. Header and bytes are generated under the same processing lock. Prefer RFC 5987 `filename*`, otherwise the quoted ASCII `filename`; a cached frontend version is not authoritative.

## Engine module interfaces (pure except ingestion input)
`backend/ingestion.py`: `inspect_file(data:bytes, filename:str, limits:dict)->dict`; `load_file(data:bytes,filename:str,options:dict,limits:dict)->pd.DataFrame`. limits keys `max_upload_bytes,max_rows,max_columns,max_uncompressed_bytes,max_expansion_ratio`. DataFrame index named `__row_id__` stable int IDs, never a data column. All column labels normalized unique strings. Errors raise ValueError. Do not silently coerce source string cells/null tokens. Infer genuinely numeric columns conservatively, preserve leading-zero identifiers. Mixed Excel scalar columns converted explicitly to lossless string representations before Parquet if necessary, documented warnings.
`backend/analysis.py`: `profile(df)->dict`, `quality(df, domain_rules:dict|None=None)->list[dict]`, `recommendations(df, issues=None)->list[dict]`, `anomalies(df,method,columns,threshold=None)->dict`.
Profile `{rows,columns,total_cells,missing_cells,missing_percentage,duplicate_rows,memory_bytes,type_distribution,empty_columns,constant_columns,column_profiles:[{name,storage_type,semantic_type,non_null_count,missing_count,missing_percentage,distinct_count,distinct_percentage,samples,common_values:[{value,count}],numeric:null|{min,max,mean,median,std,variance,q1,q3,iqr,skewness,kurtosis,zero_count,negative_count,infinity_count,percentiles,histogram:{counts,edges}},categorical:null|object,dates:null|object}],correlation:{columns,matrix}}`. JSON-safe values, no NaN/Infinity literals. No internal row IDs in column metrics.
Issue `{id,category,column,row_ids,count,severity,method,explanation,confidence,suggestion,human_review}`; row IDs bounded to 200 plus count total. Recommendation `{id,reason,column,operation:{kind,column,params},affected_records,expected_benefit,potential_data_loss,tradeoffs,requires_approval:true}`.
`backend/cleaning.py`: `apply_operation(df,operation:dict)->pd.DataFrame` (deep working copy); `preview_operation(df,operation)->dict` fields as preview endpoint except preview_id/version, use profile for before/after metrics. Kinds `trim`, `normalize_missing` (params.tokens), `drop_duplicates` (params.row_ids REQUIRED selected duplicate IDs), `to_numeric` (params.coerce bool default false), `to_date` (params.format REQUIRED, params.coerce false), `fill_missing` (params.strategy:median|mean|mode|constant, params.value), `drop_column`, `case` (params.mode:lower|upper|title), `map_categories` (params.mapping), `handle_infinity` (replace with null), `outliers` (params.row_ids explicit and params.action:remove|clip, params.lower/upper). Validate unknown params and fail explicitly. Index stable through transformations.
`backend/exports.py`: `export_data(df,format)->tuple[bytes,str,str]` bytes,mimetype,extension; `report_data(profile,issues,history,format)->tuple[bytes,str,str]`; `generate_code(operations:list[dict],language:str)->str`. Source data unmodified; escape formulas on ALL exported string cells AND headers. HTML escapes untrusted values. SQL PostgreSQL dialect reference only; unsupported operations clearly commented, never execute.

Parent owns `config.py,database.py,store.py,jobs.py,models.py,main.py` and API integration tests. Engine implementer owns `ingestion.py,analysis.py,cleaning.py,exports.py`, unit tests and synthetic samples. Frontend implementer owns `frontend/`, package manifests, frontend build/test configuration, browser tests. AI implementer owns `ai.py` and its tests. No conflicting ownership.
