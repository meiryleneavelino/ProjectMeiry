package abac

import "strings"

// Binding links a resource ("resource:<reportId>") or a security label
// ("label:<label>") to a policy. A resource binding wins over a label binding.
type Binding struct {
	Target   string `json:"target"`
	PolicyID string `json:"policyId"`
	BoundBy  string `json:"boundBy"`
	BoundAt  string `json:"boundAt"`
	TxID     string `json:"txId"`
}

// PolicyReader is the only PAP surface the PDP sees.
type PolicyReader interface {
	PolicyFor(reportID, label string) (*Policy, *Binding, error)
}

// PAP is the Policy Administration Point. Only role=admin (HospitalMSP) writes.
type PAP struct{ ctx Context }

func (p PAP) CreatePolicy(policyID, raw string) (*Policy, error) {
	return p.write(policyID, raw, true)
}

func (p PAP) UpdatePolicy(policyID, raw string) (*Policy, error) {
	return p.write(policyID, raw, false)
}

func (p PAP) write(policyID, raw string, create bool) (*Policy, error) {
	who, err := requireRole(p.ctx, RoleAdmin)
	if err != nil {
		return nil, err
	}
	body, err := parsePolicy(policyID, raw)
	if err != nil {
		return nil, err
	}
	var current Policy
	exists, err := load(p.ctx, "policy:"+policyID, &current)
	if err != nil {
		return nil, err
	}
	if create && exists {
		return nil, fail("conflict", "policy %s already exists; use UpdatePolicy", policyID)
	}
	if !create && !exists {
		return nil, fail("notfound", "policy %s does not exist", policyID)
	}
	at, err := now(p.ctx)
	if err != nil {
		return nil, err
	}
	version := current.Version + 1
	hash, err := policyHash(policyID, version, body)
	if err != nil {
		return nil, err
	}
	policy := Policy{PolicyID: policyID, Version: version, Description: body.Description, Actions: body.Actions,
		Rules: body.Rules, PolicyHash: hash, UpdatedBy: who.ID, UpdatedAt: at.Format(timeLayout), TxID: p.ctx.TxID()}
	if err := store(p.ctx, "policy:"+policyID, policy); err != nil {
		return nil, err
	}
	name := "PolicyCreated"
	if !create {
		name = "PolicyUpdated"
	}
	return &policy, emit(p.ctx, "PAP", name, who.ID, at, map[string]string{
		"policyId": policyID, "version": itoa(version), "policyHash": hash})
}

func (p PAP) BindResource(target, policyID string) (*Binding, error) {
	who, err := requireRole(p.ctx, RoleAdmin)
	if err != nil {
		return nil, err
	}
	kind, value, _ := strings.Cut(target, ":")
	switch {
	case kind == "resource" && idPattern.MatchString(value):
	case kind == "label" && labelPattern.MatchString(value):
	default:
		return nil, fail("invalid", "target must be resource:<reportId> or label:<label>")
	}
	if _, err := p.GetPolicy(policyID); err != nil {
		return nil, err
	}
	at, err := now(p.ctx)
	if err != nil {
		return nil, err
	}
	binding := Binding{Target: target, PolicyID: policyID, BoundBy: who.ID, BoundAt: at.Format(timeLayout), TxID: p.ctx.TxID()}
	if err := store(p.ctx, "bind:"+target, binding); err != nil {
		return nil, err
	}
	return &binding, emit(p.ctx, "PAP", "ResourceBound", who.ID, at, map[string]string{"target": target, "policyId": policyID})
}

func (p PAP) GetPolicy(policyID string) (*Policy, error) {
	var policy Policy
	found, err := load(p.ctx, "policy:"+policyID, &policy)
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, fail("notfound", "policy %s does not exist", policyID)
	}
	return &policy, nil
}

// PolicyFor resolves the policy of a resource: resource binding, then label
// binding, else none (the PDP then denies: deny by default).
func (p PAP) PolicyFor(reportID, label string) (*Policy, *Binding, error) {
	for _, target := range []string{"resource:" + reportID, "label:" + label} {
		if strings.HasSuffix(target, ":") {
			continue
		}
		var binding Binding
		found, err := load(p.ctx, "bind:"+target, &binding)
		if err != nil {
			return nil, nil, err
		}
		if found {
			policy, err := p.GetPolicy(binding.PolicyID)
			if err != nil {
				return nil, nil, err
			}
			return policy, &binding, nil
		}
	}
	return nil, nil, nil
}

// PolicyCatalog lists every policy with the targets bound to it.
type PolicyCatalog struct {
	Policies []Policy  `json:"policies"`
	Bindings []Binding `json:"bindings"`
}

func (p PAP) ListPolicies() (*PolicyCatalog, error) {
	policies, err := list[Policy](p.ctx, "policy:")
	if err != nil {
		return nil, err
	}
	bindings, err := list[Binding](p.ctx, "bind:")
	return &PolicyCatalog{Policies: policies, Bindings: bindings}, err
}
