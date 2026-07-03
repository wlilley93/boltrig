// The admin section custom editors: dedicated typed controls for the flagship
// shapes SchemaFormV2 cannot express from a schema alone (the RBAC role-mapping
// rows and the open key/value maps). A section descriptor pins one of these on a
// property via `editor`, and SchemaFormV2 renders it instead of a JSON blob.

export { RoleMappingList } from "./roleMappings";
export { NotificationDefaultsList, PriceList, SkillsByRoleList } from "./keyValueList";
