// The Boltrig mark: a lightning bolt between two "rig" bracket uprights.
export function BoltMark() {
  return (
    <svg className="side__mark" viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
      <path d="M7.5 3.5H4.5V20.5H7.5" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
      <path d="M16.5 3.5H19.5V20.5H16.5" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
      <path d="M13.2 4.5L8.5 12.6H12L10.8 19.5L15.5 11.4H12L13.2 4.5Z" fill="currentColor" />
    </svg>
  );
}
