import { useMemo, useState } from 'react';
import { Check, ChevronsUpDown } from 'lucide-react';

import { cn } from './utils';
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from './command';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from './popover';

export interface SearchableSelectOption {
  value: string;
  label: string;
  description?: string | null;
  keywords?: string[];
}

interface SearchableSelectProps {
  value: string;
  options: SearchableSelectOption[];
  onChange: (value: string) => void;
  placeholder: string;
  searchPlaceholder?: string;
  emptyLabel?: string;
  disabled?: boolean;
  allowClear?: boolean;
  clearLabel?: string;
  triggerClassName?: string;
  contentClassName?: string;
}

export function SearchableSelect({
  value,
  options,
  onChange,
  placeholder,
  searchPlaceholder = 'Search...',
  emptyLabel = 'No results found.',
  disabled = false,
  allowClear = false,
  clearLabel = 'Clear selection',
  triggerClassName,
  contentClassName,
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);

  const selectedOption = useMemo(
    () => options.find((option) => option.value === value) || null,
    [options, value],
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className={cn(
            'flex min-h-[44px] w-full items-center justify-between rounded-xl border border-gray-300 px-4 py-2.5 text-left text-sm text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:opacity-60',
            !selectedOption && 'text-gray-500',
            triggerClassName,
          )}
        >
          <span className="min-w-0 truncate">{selectedOption?.label || placeholder}</span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 text-gray-400" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className={cn('w-[var(--radix-popover-trigger-width)] min-w-[260px] p-0', contentClassName)}
      >
        <Command shouldFilter>
          <CommandInput placeholder={searchPlaceholder} />
          <CommandList className="max-h-64">
            <CommandEmpty>{emptyLabel}</CommandEmpty>
            {allowClear && (
              <CommandItem
                value="__clear__"
                onSelect={() => {
                  onChange('');
                  setOpen(false);
                }}
              >
                <span className="truncate">{clearLabel}</span>
              </CommandItem>
            )}
            {options.map((option) => (
              <CommandItem
                key={option.value}
                value={[option.label, option.description, ...(option.keywords || [])].filter(Boolean).join(' ')}
                onSelect={() => {
                  onChange(option.value);
                  setOpen(false);
                }}
              >
                <Check className={cn('h-4 w-4', value === option.value ? 'opacity-100' : 'opacity-0')} />
                <div className="min-w-0">
                  <div className="truncate">{option.label}</div>
                  {option.description ? (
                    <div className="truncate text-xs text-gray-500">{option.description}</div>
                  ) : null}
                </div>
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
