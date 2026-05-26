import React, { useEffect, useState } from 'react';
import Box from '@mui/material/Box';
import TextField from '@mui/material/TextField';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ClickAwayListener from '@mui/material/ClickAwayListener';
import CheckIcon from '@mui/icons-material/Check';
import CloseIcon from '@mui/icons-material/Close';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import type { SxProps, Theme } from '@mui/material/styles';

interface InlineEditableSessionNameProps {
  value: string;
  onCommit: (nextValue: string) => void | Promise<void>;
  textSx?: SxProps<Theme>;
  containerSx?: SxProps<Theme>;
  inputSx?: SxProps<Theme>;
  buttonSize?: 'small' | 'medium';
  placeholder?: string;
  disabled?: boolean;
}

const InlineEditableSessionName: React.FC<InlineEditableSessionNameProps> = ({
  value,
  onCommit,
  textSx,
  containerSx,
  inputSx,
  buttonSize = 'small',
  placeholder = 'Untitled',
  disabled = false,
}) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    if (!editing) {
      setDraft(value);
    }
  }, [editing, value]);

  const startEditing = () => {
    if (disabled) return;
    setDraft(value);
    setEditing(true);
  };

  const cancelEditing = () => {
    setDraft(value);
    setEditing(false);
  };

  const submit = async () => {
    const next = draft.trim();
    const previous = value.trim();
    if (!next || next === previous) {
      cancelEditing();
      return;
    }
    await onCommit(next);
    setEditing(false);
  };

  if (editing) {
    return (
      <ClickAwayListener onClickAway={cancelEditing}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0, ...containerSx }}>
          <TextField
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                void submit();
              } else if (e.key === 'Escape') {
                e.preventDefault();
                cancelEditing();
              }
            }}
            autoFocus
            size="small"
            placeholder={placeholder}
            variant="outlined"
            sx={{
              minWidth: 0,
              '& .MuiInputBase-root': {
                height: 30,
                fontSize: 'inherit',
                fontWeight: 600,
                color: 'inherit',
                bgcolor: 'transparent',
              },
              '& .MuiInputBase-input': {
                py: 0.5,
                px: 1,
              },
              ...inputSx,
            }}
          />
          <Tooltip title="Save rename" arrow>
            <IconButton size={buttonSize} onClick={() => void submit()} sx={{ flexShrink: 0 }}>
              <CheckIcon sx={{ fontSize: 16 }} />
            </IconButton>
          </Tooltip>
          <Tooltip title="Cancel" arrow>
            <IconButton size={buttonSize} onClick={cancelEditing} sx={{ flexShrink: 0 }}>
              <CloseIcon sx={{ fontSize: 16 }} />
            </IconButton>
          </Tooltip>
        </Box>
      </ClickAwayListener>
    );
  }

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0, ...containerSx }}>
      <Typography noWrap onDoubleClick={startEditing} sx={{ minWidth: 0, ...textSx }}>
        {value || placeholder}
      </Typography>
      {!disabled && (
        <Tooltip title="Rename" arrow>
          <IconButton
            size={buttonSize}
            onClick={startEditing}
            sx={{ flexShrink: 0, color: 'inherit', opacity: 0.75, '&:hover': { opacity: 1 } }}
          >
            <EditOutlinedIcon sx={{ fontSize: 16 }} />
          </IconButton>
        </Tooltip>
      )}
    </Box>
  );
};

export default InlineEditableSessionName;