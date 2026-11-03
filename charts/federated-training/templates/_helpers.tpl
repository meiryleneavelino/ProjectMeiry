{{- define "training.sidecar" -}}
- name: sidecar
  image: {{ .Values.integrated.image | quote }}
  imagePullPolicy: IfNotPresent
  command: [/app/sidecar]
  env:
    - name: AMQ_USER
      value: normal_user
    - name: AMQ_PASSWORD
      valueFrom:
        secretKeyRef:
          name: rabbit
          key: password
    - name: OC_AGENT_HOST
      value: collector.core.svc.cluster.local:55678
  readinessProbe:
    tcpSocket:
      port: 50051
    initialDelaySeconds: 2
  securityContext:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop: [ALL]
  resources:
    requests:
      cpu: 50m
      memory: 64Mi
    limits:
      cpu: 300m
      memory: 256Mi
{{- end }}