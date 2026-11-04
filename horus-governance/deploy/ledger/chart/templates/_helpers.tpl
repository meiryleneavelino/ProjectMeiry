{{- define "ledger.security" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  seccompProfile:
    type: RuntimeDefault
{{- end -}}

{{- define "ledger.container" -}}
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop: [ALL]
{{- end -}}

{{- define "ledger.waitCrypto" -}}
- name: wait-for-identities
  image: {{ .image }}
  command: [sh, -c, "until [ -f /crypto/.complete ]; do echo waiting for enrollment; sleep 3; done"]
  {{- include "ledger.container" . | nindent 2 }}
  volumeMounts:
    - name: crypto
      mountPath: /crypto
      readOnly: true
{{- end -}}
