import React, { useEffect, useState, useCallback } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import { API_BASE } from '@/shared/config';
import { useClaudeTokens } from '@/shared/styles/ThemeContext';

const TRUSTED_BASH_API = `${API_BASE}/tools/trusted-bash-commands`;

type BashRule = { kind: 'exact' | 'prefix' | 'type'; value: string };

const RULE_LABELS: Record<BashRule['kind'], string> = {
  exact: 'Exact command',
  prefix: 'Command prefix',
  type: 'Command type',
};

export const TrustedBashCommands: React.FC = () => {
  const c = useClaudeTokens();
  const [rules, setRules] = useState<BashRule[] | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(TRUSTED_BASH_API);
      if (!res.ok) return;
      const data = await res.json();
      const incoming = Array.isArray(data.rules) ? data.rules : [];
      setRules(
        incoming.filter((rule): rule is BashRule => !!rule && (rule.kind === 'exact' || rule.kind === 'prefix' || rule.kind === 'type') && typeof rule.value === 'string' && rule.value.trim())
      );
    } catch {
      setRules([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const revoke = useCallback(async (rule: BashRule) => {
    if (!rules) return;
    const next = rules.filter((r) => !(r.kind === rule.kind && r.value === rule.value));
    setRules(next);
    try {
      await fetch(TRUSTED_BASH_API, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rules: next }),
      });
    } catch {
      load();
    }
  }, [rules, load]);

  if (!rules || rules.length === 0) return null;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Typography sx={{ fontSize: '0.7rem', color: c.text.ghost, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>
        Trusted Bash commands
      </Typography>
      <Typography sx={{ fontSize: '0.8rem', color: c.text.secondary, lineHeight: 1.45 }}>
        Bash commands you chose to always allow appear below. Remove one to start asking again.
      </Typography>
      <Box sx={{ display: 'flex', flexDirection: 'column', border: `1px solid ${c.border.subtle}`, borderRadius: 1.5, overflow: 'hidden', mt: 0.5 }}>
        {rules.map((rule, idx) => (
          <Box
            key={`${rule.kind}:${rule.value}`}
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              px: 1.5,
              py: 1,
              borderTop: idx === 0 ? 'none' : `1px solid ${c.border.subtle}`,
              bgcolor: c.bg.surface,
            }}
          >
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography sx={{ fontSize: '0.82rem', color: c.text.primary, fontWeight: 500 }}>
                {RULE_LABELS[rule.kind]}
              </Typography>
              <Typography sx={{ fontSize: '0.72rem', color: c.text.tertiary, fontFamily: c.font.mono, mt: 0.15 }}>
                {rule.value}
              </Typography>
            </Box>
            <IconButton
              size="small"
              onClick={() => revoke(rule)}
              aria-label={`Remove ${RULE_LABELS[rule.kind]} ${rule.value}`}
              sx={{ color: c.text.tertiary, '&:hover': { color: c.status.error } }}
            >
              <DeleteOutlineIcon sx={{ fontSize: 18 }} />
            </IconButton>
          </Box>
        ))}
      </Box>
    </Box>
  );
};

export default TrustedBashCommands;