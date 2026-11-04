package abac

type handler struct {
	arity int
	call  func(Context, []string) (any, error)
}

func components(ctx Context) (PAP, PIP, PDP) {
	pap, pip := PAP{ctx}, PIP{ctx}
	return pap, pip, PDP{ctx: ctx, pap: pap, pip: pip}
}

// One chaincode, three contracts: functions are named "<Component>:<Name>".
var handlers = map[string]handler{
	"PAP:CreatePolicy": {2, func(c Context, a []string) (any, error) {
		pap, _, _ := components(c)
		return pap.CreatePolicy(a[0], a[1])
	}},
	"PAP:UpdatePolicy": {2, func(c Context, a []string) (any, error) {
		pap, _, _ := components(c)
		return pap.UpdatePolicy(a[0], a[1])
	}},
	"PAP:GetPolicy":    {1, func(c Context, a []string) (any, error) { pap, _, _ := components(c); return pap.GetPolicy(a[0]) }},
	"PAP:ListPolicies": {0, func(c Context, a []string) (any, error) { pap, _, _ := components(c); return pap.ListPolicies() }},
	"PAP:BindResource": {2, func(c Context, a []string) (any, error) {
		pap, _, _ := components(c)
		return pap.BindResource(a[0], a[1])
	}},
	"PAP:GetPolicyForResource": {2, func(c Context, a []string) (any, error) {
		pap, _, _ := components(c)
		policy, binding, err := pap.PolicyFor(a[0], a[1])
		if err == nil && policy == nil {
			err = fail("notfound", "no policy bound to resource %s or label %s", a[0], a[1])
		}
		return map[string]any{"policy": policy, "binding": binding}, err
	}},

	"PIP:PutConsent": {6, func(c Context, a []string) (any, error) {
		_, pip, _ := components(c)
		return pip.PutConsent(a[0], a[1], a[2], a[3], a[4], a[5])
	}},
	"PIP:RevokeConsent": {1, func(c Context, a []string) (any, error) { _, pip, _ := components(c); return pip.RevokeConsent(a[0]) }},
	"PIP:GetConsent":    {1, func(c Context, a []string) (any, error) { _, pip, _ := components(c); return pip.GetConsent(a[0]) }},
	"PIP:GetConsentFor": {2, func(c Context, a []string) (any, error) {
		_, pip, _ := components(c)
		return pip.GetConsentFor(a[0], a[1])
	}},
	"PIP:ListConsents": {0, func(c Context, a []string) (any, error) { _, pip, _ := components(c); return pip.ListConsents() }},
	"PIP:PutResource": {6, func(c Context, a []string) (any, error) {
		_, pip, _ := components(c)
		return pip.PutResource(a[0], a[1], a[2], a[3], a[4], a[5])
	}},
	"PIP:GetResource":   {1, func(c Context, a []string) (any, error) { _, pip, _ := components(c); return pip.GetResource(a[0]) }},
	"PIP:ListResources": {0, func(c Context, a []string) (any, error) { _, pip, _ := components(c); return pip.ListResources() }},

	"PDP:RequestAccess": {2, func(c Context, a []string) (any, error) {
		_, _, pdp := components(c)
		return pdp.RequestAccess(a[0], a[1])
	}},
	"PDP:GetDecision": {1, func(c Context, a []string) (any, error) { _, _, pdp := components(c); return pdp.GetDecision(a[0]) }},

	"ListEvents": {0, func(c Context, a []string) (any, error) { return list[Event](c, "evt:") }},
	"WhoAmI":     {0, func(c Context, a []string) (any, error) { return subject(c) }},
}

// Invoke routes a chaincode call and returns canonical JSON.
func Invoke(ctx Context, function string, args []string) ([]byte, error) {
	route, found := handlers[function]
	if !found {
		return nil, fail("invalid", "unknown function %q", function)
	}
	if len(args) != route.arity {
		return nil, fail("invalid", "%s expects %d arguments, got %d", function, route.arity, len(args))
	}
	result, err := route.call(ctx, args)
	if err != nil {
		return nil, err
	}
	return Canonical(result)
}
