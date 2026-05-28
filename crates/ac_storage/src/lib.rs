use ac_core::{AggregateError, RunAggregate};
use ac_protocol::{RunEvent, RunId, RunProjection, StoredRunEvent};
use chrono::{DateTime, Utc};
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Clone)]
pub struct RunPaths {
    pub run_dir: PathBuf,
    pub events_file: PathBuf,
    pub snapshot_file: PathBuf,
}

#[derive(Debug, Error)]
pub enum StorageError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("aggregate error: {0}")]
    Aggregate(#[from] AggregateError),
    #[error("run {0} has no events")]
    MissingRun(RunId),
}

#[derive(Debug, Clone)]
pub struct FileRunStore {
    base_dir: PathBuf,
}

impl FileRunStore {
    pub fn new(base_dir: impl Into<PathBuf>) -> Self {
        Self {
            base_dir: base_dir.into(),
        }
    }

    pub fn base_dir(&self) -> &Path {
        &self.base_dir
    }

    pub fn paths(&self, run_id: &RunId) -> RunPaths {
        let run_dir = self.base_dir.join(run_id.as_str());
        RunPaths {
            run_dir: run_dir.clone(),
            events_file: run_dir.join("events.jsonl"),
            snapshot_file: run_dir.join("snapshot.json"),
        }
    }

    pub fn list_run_ids(&self) -> Result<Vec<RunId>, StorageError> {
        if !self.base_dir.exists() {
            return Ok(Vec::new());
        }

        let mut runs = Vec::new();
        for entry in fs::read_dir(&self.base_dir)? {
            let entry = entry?;
            if entry.file_type()?.is_dir() {
                runs.push(RunId::from(entry.file_name().to_string_lossy().to_string()));
            }
        }
        runs.sort_by(|left, right| left.as_str().cmp(right.as_str()));
        Ok(runs)
    }

    pub fn append_events(
        &self,
        run_id: &RunId,
        events: &[RunEvent],
        emitted_at: DateTime<Utc>,
    ) -> Result<Vec<StoredRunEvent>, StorageError> {
        let paths = self.paths(run_id);
        fs::create_dir_all(&paths.run_dir)?;
        let starting_sequence = self
            .load_events(run_id)?
            .last()
            .map(|event| event.sequence)
            .unwrap_or(0);

        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&paths.events_file)?;

        let mut stored = Vec::with_capacity(events.len());
        for (idx, event) in events.iter().enumerate() {
            let envelope = StoredRunEvent {
                sequence: starting_sequence + idx as u64 + 1,
                run_id: run_id.clone(),
                emitted_at,
                event: event.clone(),
            };
            serde_json::to_writer(&mut file, &envelope)?;
            file.write_all(b"\n")?;
            stored.push(envelope);
        }

        Ok(stored)
    }

    pub fn load_events(&self, run_id: &RunId) -> Result<Vec<StoredRunEvent>, StorageError> {
        let paths = self.paths(run_id);
        if !paths.events_file.exists() {
            return Ok(Vec::new());
        }

        let reader = BufReader::new(File::open(paths.events_file)?);
        let mut events = Vec::new();
        for line in reader.lines() {
            let line = line?;
            if line.trim().is_empty() {
                continue;
            }
            events.push(serde_json::from_str::<StoredRunEvent>(&line)?);
        }
        Ok(events)
    }

    pub fn save_snapshot(
        &self,
        run_id: &RunId,
        projection: &RunProjection,
    ) -> Result<(), StorageError> {
        let paths = self.paths(run_id);
        fs::create_dir_all(&paths.run_dir)?;
        fs::write(
            paths.snapshot_file,
            serde_json::to_string_pretty(projection)?,
        )?;
        Ok(())
    }

    pub fn load_snapshot(&self, run_id: &RunId) -> Result<Option<RunProjection>, StorageError> {
        let paths = self.paths(run_id);
        if !paths.snapshot_file.exists() {
            return Ok(None);
        }
        Ok(Some(serde_json::from_str::<RunProjection>(
            &fs::read_to_string(paths.snapshot_file)?,
        )?))
    }

    pub fn rebuild_projection(&self, run_id: &RunId) -> Result<RunProjection, StorageError> {
        let events = self.load_events(run_id)?;
        if events.is_empty() {
            return Err(StorageError::MissingRun(run_id.clone()));
        }
        let aggregate = RunAggregate::replay(&events)?;
        Ok(aggregate.projection()?)
    }
}
